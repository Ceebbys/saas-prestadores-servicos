import json
import logging

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from apps.core.mixins import EmpresaMixin, HtmxResponseMixin

from .forms import (
    ChatbotActionForm,
    ChatbotChoiceFormSet,
    ChatbotFlowForm,
    ChatbotStepForm,
)
from .models import ChatbotAction, ChatbotChoice, ChatbotFlow, ChatbotSession, ChatbotStep
from .services import process_response, start_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Flow CRUD
# ---------------------------------------------------------------------------


class FlowListView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = ChatbotFlow
    template_name = "chatbot/flow_list.html"
    partial_template_name = "chatbot/partials/_flow_table.html"
    context_object_name = "flows"
    paginate_by = 25


class FlowCreateView(EmpresaMixin, HtmxResponseMixin, CreateView):
    model = ChatbotFlow
    form_class = ChatbotFlowForm
    template_name = "chatbot/flow_form.html"
    partial_template_name = "chatbot/partials/_flow_form.html"
    success_url = reverse_lazy("chatbot:flow_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Fluxo de chatbot criado com sucesso.")
        return response


class FlowDetailView(EmpresaMixin, DetailView):
    model = ChatbotFlow
    template_name = "chatbot/flow_detail.html"
    context_object_name = "flow"

    def get_queryset(self):
        return super().get_queryset().prefetch_related(
            "steps__choices", "actions"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        steps = list(
            self.object.steps.prefetch_related("choices").order_by("order")
        )
        steps_json = json.dumps(
            [
                {
                    "id": s.id,
                    "order": s.order,
                    "question": s.question_text,
                    "type": s.step_type,
                    "required": s.is_required,
                    "mapping": s.lead_field_mapping,
                    "choices": [
                        {"text": c.text, "next_step": c.next_step_id}
                        for c in s.choices.order_by("order")
                    ],
                }
                for s in steps
            ]
        )
        context["steps_json"] = steps_json
        context["steps"] = steps
        context["actions"] = self.object.actions.all()
        return context


class FlowUpdateView(EmpresaMixin, HtmxResponseMixin, UpdateView):
    model = ChatbotFlow
    form_class = ChatbotFlowForm
    template_name = "chatbot/flow_form.html"
    partial_template_name = "chatbot/partials/_flow_form.html"
    success_url = reverse_lazy("chatbot:flow_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["steps"] = self.object.steps.prefetch_related(
            "choices"
        ).order_by("codigo_hierarquico", "order")
        context["steps_tree"] = self.object.steps_tree()
        context["actions"] = self.object.actions.all()
        context["step_form"] = ChatbotStepForm(flow=self.object)
        context["action_form"] = ChatbotActionForm()
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Fluxo atualizado com sucesso.")
        return response


class FlowDeleteView(EmpresaMixin, DeleteView):
    model = ChatbotFlow
    success_url = reverse_lazy("chatbot:flow_list")
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        messages.success(request, "Fluxo excluído com sucesso.")
        return self.delete(request, *args, **kwargs)


class FlowBuilderView(EmpresaMixin, DetailView):
    """RV06 — Tela host do React Flow island.

    Renderiza `flow_builder.html` que monta o bundle React no `<div id=root>`.
    O bundle lê dados-* attributes para descobrir endpoints e CSRF token.

    Multi-tenant validado via EmpresaMixin (queryset filtrado).
    """

    model = ChatbotFlow
    template_name = "chatbot/flow_builder.html"
    context_object_name = "flow"

    def get_queryset(self):
        return super().get_queryset().filter(empresa=self.request.empresa)

    def get_context_data(self, **kwargs):
        from apps.chatbot.builder.api.views import _EMPTY_GRAPH, _get_or_create_draft

        ctx = super().get_context_data(**kwargs)
        draft = _get_or_create_draft(self.object, self.request.user)
        ctx["initial_graph"] = draft.graph_json or _EMPTY_GRAPH
        ctx["draft_version_id"] = draft.id
        ctx["has_published"] = self.object.current_published_version_id is not None
        return ctx


class FlowToggleView(EmpresaMixin, View):
    """Ativa/desativa um fluxo de chatbot."""

    def post(self, request, pk):
        flow = get_object_or_404(ChatbotFlow, pk=pk, empresa=request.empresa)
        flow.is_active = not flow.is_active
        flow.save(update_fields=["is_active", "updated_at"])
        status = "ativado" if flow.is_active else "desativado"
        messages.success(request, f"Fluxo {status} com sucesso.")
        return redirect("chatbot:flow_list")


# ---------------------------------------------------------------------------
# Step Management (inline)
# ---------------------------------------------------------------------------


class StepAddView(EmpresaMixin, View):
    """Adiciona um passo ao fluxo."""

    def post(self, request, pk):
        flow = get_object_or_404(ChatbotFlow, pk=pk, empresa=request.empresa)
        form = ChatbotStepForm(request.POST, flow=flow)
        if form.is_valid():
            step = form.save(commit=False)
            step.flow = flow
            step.save()

            # Handle choices for 'choice' type
            choices_text = request.POST.get("choices_text", "").strip()
            if step.step_type == "choice" and choices_text:
                for i, text in enumerate(choices_text.split("\n")):
                    text = text.strip()
                    if text:
                        ChatbotChoice.objects.create(
                            step=step, text=text, order=i
                        )

            messages.success(request, "Passo adicionado com sucesso.")
        return redirect("chatbot:flow_update", pk=flow.pk)


class StepUpdateView(EmpresaMixin, View):
    """Atualiza um passo do fluxo."""

    def post(self, request, pk, step_pk):
        flow = get_object_or_404(ChatbotFlow, pk=pk, empresa=request.empresa)
        step = get_object_or_404(ChatbotStep, pk=step_pk, flow=flow)
        form = ChatbotStepForm(request.POST, instance=step, flow=flow)
        if form.is_valid():
            form.save()

            # Rebuild choices if step_type is 'choice'
            choices_text = request.POST.get("choices_text", "").strip()
            if step.step_type == "choice":
                step.choices.all().delete()
                if choices_text:
                    for i, text in enumerate(choices_text.split("\n")):
                        text = text.strip()
                        if text:
                            ChatbotChoice.objects.create(
                                step=step, text=text, order=i
                            )

            messages.success(request, "Passo atualizado com sucesso.")
        return redirect("chatbot:flow_update", pk=flow.pk)


class StepDeleteView(EmpresaMixin, View):
    """Remove um passo do fluxo."""

    def post(self, request, pk, step_pk):
        flow = get_object_or_404(ChatbotFlow, pk=pk, empresa=request.empresa)
        ChatbotStep.objects.filter(pk=step_pk, flow=flow).delete()
        messages.success(request, "Passo removido com sucesso.")
        return redirect("chatbot:flow_update", pk=flow.pk)


class StepChoicesEditView(EmpresaMixin, View):
    """Editor de ramificações: define `next_step` para cada choice de uma etapa.

    GET: renderiza um inline formset com todas as choices da etapa.
    POST: salva o formset (cria/edita/remove choices).
    """

    template_name = "chatbot/partials/_choice_form.html"

    def _get_form_kwargs_for_choices(self, formset, flow, step):
        """Injeta `flow` e `exclude_step` em cada form do formset."""
        for form in formset.forms:
            # Hack para passar params extras: setamos no field queryset diretamente.
            qs = ChatbotStep.objects.filter(flow=flow).order_by("order")
            qs = qs.exclude(pk=step.pk)
            form.fields["next_step"].queryset = qs
            form.fields["next_step"].required = False
            form.fields["next_step"].empty_label = "(linear — próximo na ordem)"

    def get(self, request, pk, step_pk):
        flow = get_object_or_404(ChatbotFlow, pk=pk, empresa=request.empresa)
        step = get_object_or_404(ChatbotStep, pk=step_pk, flow=flow)
        formset = ChatbotChoiceFormSet(instance=step, prefix=f"choices-{step.pk}")
        self._get_form_kwargs_for_choices(formset, flow, step)
        return render(request, self.template_name, {
            "flow": flow, "step": step, "formset": formset,
        })

    def post(self, request, pk, step_pk):
        flow = get_object_or_404(ChatbotFlow, pk=pk, empresa=request.empresa)
        step = get_object_or_404(ChatbotStep, pk=step_pk, flow=flow)
        formset = ChatbotChoiceFormSet(
            request.POST, instance=step, prefix=f"choices-{step.pk}"
        )
        self._get_form_kwargs_for_choices(formset, flow, step)
        if formset.is_valid():
            formset.save()
            messages.success(request, "Opções de resposta atualizadas.")
            if request.htmx:
                # Re-render the partial with fresh state
                fresh_formset = ChatbotChoiceFormSet(
                    instance=step, prefix=f"choices-{step.pk}"
                )
                self._get_form_kwargs_for_choices(fresh_formset, flow, step)
                return render(request, self.template_name, {
                    "flow": flow, "step": step,
                    "formset": fresh_formset, "saved": True,
                })
            return redirect("chatbot:flow_update", pk=flow.pk)
        return render(request, self.template_name, {
            "flow": flow, "step": step, "formset": formset,
        })


# ---------------------------------------------------------------------------
# Action Management (inline)
# ---------------------------------------------------------------------------


class ActionAddView(EmpresaMixin, View):
    """Adiciona uma ação ao fluxo."""

    def post(self, request, pk):
        flow = get_object_or_404(ChatbotFlow, pk=pk, empresa=request.empresa)
        form = ChatbotActionForm(request.POST, flow=flow)
        if form.is_valid():
            action = form.save(commit=False)
            action.flow = flow
            action.save()
            messages.success(request, "Ação adicionada com sucesso.")
        else:
            for field, errors in form.errors.items():
                for e in errors:
                    messages.error(request, f"{field}: {e}")
        return redirect("chatbot:flow_update", pk=flow.pk)


class ActionDeleteView(EmpresaMixin, View):
    """Remove uma ação do fluxo."""

    def post(self, request, pk, action_pk):
        flow = get_object_or_404(ChatbotFlow, pk=pk, empresa=request.empresa)
        ChatbotAction.objects.filter(pk=action_pk, flow=flow).delete()
        messages.success(request, "Ação removida com sucesso.")
        return redirect("chatbot:flow_update", pk=flow.pk)


# ---------------------------------------------------------------------------
# Public Chat View (sem autenticação)
# ---------------------------------------------------------------------------


def public_chat(request, token):
    """Página pública de chat — qualquer visitante pode usar."""
    flow = get_object_or_404(ChatbotFlow, webhook_token=token, is_active=True)
    return render(request, "chatbot/public_chat.html", {
        "flow": flow,
        "token": token,
    })


# ---------------------------------------------------------------------------
# API JSON (sem autenticação, CSRF exempt)
# ---------------------------------------------------------------------------


def _get_flow_by_token(token):
    return ChatbotFlow.objects.filter(
        webhook_token=token, is_active=True,
    ).first()


@csrf_exempt
@require_POST
def api_start_session(request, token):
    """Inicia uma sessão de chatbot. POST com JSON opcional {channel, sender_id}."""
    flow = _get_flow_by_token(token)
    if not flow:
        return JsonResponse({"error": "Flow not found or inactive"}, status=404)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        body = {}

    channel = body.get("channel", "webchat")
    sender_id = body.get("sender_id", "")

    try:
        result = start_session(flow, channel=channel, sender_id=sender_id)
        return JsonResponse(result)
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)


@csrf_exempt
@require_POST
def api_respond(request, token):
    """Processa resposta do usuário. POST com JSON {session_key, response}."""
    flow = _get_flow_by_token(token)
    if not flow:
        return JsonResponse({"error": "Flow not found or inactive"}, status=404)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    session_key = body.get("session_key", "")
    user_response = body.get("response", "")

    if not session_key or not user_response:
        return JsonResponse(
            {"error": "session_key and response are required"}, status=400,
        )

    try:
        result = process_response(session_key, user_response)
        return JsonResponse(result)
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)


# ---------------------------------------------------------------------------
# Webhook funcional (integração WhatsApp / genérica)
# ---------------------------------------------------------------------------


@csrf_exempt
def webhook_receive(request, token):
    """Endpoint de webhook para integração com WhatsApp Business API e outros canais.

    Recebe mensagens, gerencia sessões automaticamente, e retorna resposta JSON.
    Para cada sender_id: cria nova sessão se não existir, ou continua a existente.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    flow = _get_flow_by_token(token)
    if not flow:
        return JsonResponse({"error": "Flow not found or inactive"}, status=404)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    sender_id = body.get("sender_id", body.get("from", ""))
    message = body.get("message", body.get("text", ""))

    if not sender_id:
        return JsonResponse({"error": "sender_id is required"}, status=400)

    # Buscar sessão ativa para este sender_id
    session = ChatbotSession.objects.filter(
        flow=flow, sender_id=sender_id, status=ChatbotSession.Status.ACTIVE,
    ).first()

    if not session:
        # Iniciar nova sessão
        try:
            result = start_session(flow, channel="whatsapp", sender_id=sender_id)
            return JsonResponse({
                "status": "ok",
                "session_key": result["session_key"],
                "reply": result["welcome_message"],
                "question": result["step"]["question"] if result.get("step") else None,
                "choices": result["step"]["choices"] if result.get("step") else [],
                "is_complete": False,
            })
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=400)

    # Processar resposta na sessão existente
    if not message:
        return JsonResponse({
            "status": "ok",
            "reply": session.current_step.question_text if session.current_step else "",
            "is_complete": False,
        })

    try:
        result = process_response(str(session.session_key), message)
        reply = ""
        choices = []

        if result.get("error"):
            reply = result["message"]
            choices = result["step"]["choices"] if result.get("step") else []
        elif result.get("is_complete"):
            reply = result["message"]
        elif result.get("step"):
            reply = result["step"]["question"]
            choices = result["step"]["choices"]

        return JsonResponse({
            "status": "ok",
            "session_key": str(session.session_key),
            "reply": reply,
            "choices": choices,
            "is_complete": result.get("is_complete", False),
            "lead_id": result.get("lead_id"),
        })
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)
