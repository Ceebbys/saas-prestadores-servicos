import json

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from apps.core.mixins import EmpresaMixin, HtmxResponseMixin

from .forms import ChatbotActionForm, ChatbotFlowForm, ChatbotStepForm
from .models import ChatbotAction, ChatbotChoice, ChatbotFlow, ChatbotStep


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
        ).order_by("order")
        context["actions"] = self.object.actions.all()
        context["step_form"] = ChatbotStepForm()
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
        form = ChatbotStepForm(request.POST)
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
        form = ChatbotStepForm(request.POST, instance=step)
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


# ---------------------------------------------------------------------------
# Action Management (inline)
# ---------------------------------------------------------------------------


class ActionAddView(EmpresaMixin, View):
    """Adiciona uma ação ao fluxo."""

    def post(self, request, pk):
        flow = get_object_or_404(ChatbotFlow, pk=pk, empresa=request.empresa)
        form = ChatbotActionForm(request.POST)
        if form.is_valid():
            action = form.save(commit=False)
            action.flow = flow
            action.save()
            messages.success(request, "Ação adicionada com sucesso.")
        return redirect("chatbot:flow_update", pk=flow.pk)


class ActionDeleteView(EmpresaMixin, View):
    """Remove uma ação do fluxo."""

    def post(self, request, pk, action_pk):
        flow = get_object_or_404(ChatbotFlow, pk=pk, empresa=request.empresa)
        ChatbotAction.objects.filter(pk=action_pk, flow=flow).delete()
        messages.success(request, "Ação removida com sucesso.")
        return redirect("chatbot:flow_update", pk=flow.pk)


# ---------------------------------------------------------------------------
# Webhook (stub)
# ---------------------------------------------------------------------------


@csrf_exempt
def webhook_receive(request, token):
    """
    Endpoint de webhook para integração futura com WhatsApp Business API.

    STUB — aceita POST, valida o token, retorna JSON.

    Na integração real, este endpoint:
    1. Receberá mensagens do WhatsApp via webhook
    2. Identificará a sessão do usuário
    3. Chamará process_chatbot_response() para processar
    4. Retornará a próxima mensagem do fluxo
    """
    if request.method != "POST":
        return JsonResponse(
            {"error": "Method not allowed"}, status=405
        )

    flow = ChatbotFlow.objects.filter(
        webhook_token=token, is_active=True
    ).first()

    if not flow:
        return JsonResponse(
            {"error": "Flow not found or inactive"}, status=404
        )

    return JsonResponse(
        {
            "status": "ok",
            "message": "Webhook received (stub)",
            "flow": flow.name,
            "integration_ready": True,
        }
    )
