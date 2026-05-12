"""Views da inbox unificada de comunicações."""
from __future__ import annotations

import logging

from django.contrib import messages as django_messages
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View
from django.views.generic import ListView, DetailView

from apps.core.mixins import EmpresaMixin, HtmxResponseMixin
from apps.communications.forms import (
    AssignConversationForm,
    ConversationStatusForm,
    QuickActionForm,
    SendMessageForm,
)
from apps.communications.models import Conversation, ConversationMessage
from apps.communications.services import (
    add_internal_note,
    send_email,
    send_whatsapp,
)

logger = logging.getLogger(__name__)


class InboxView(EmpresaMixin, HtmxResponseMixin, ListView):
    """Inbox 3 colunas (mobile: stack). HTMX para refresh da lista."""

    model = Conversation
    template_name = "communications/inbox.html"
    partial_template_name = "communications/partials/_conversation_list.html"
    context_object_name = "conversations"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            Conversation.objects
            .filter(empresa=self.request.empresa)
            .select_related("lead", "contato", "assigned_to")
            .order_by("-last_message_at", "-created_at")
        )
        # Filtros opcionais
        status = self.request.GET.get("status", "").strip()
        if status and status != "all":
            qs = qs.filter(status=status)
        q = (self.request.GET.get("q", "") or "").strip()
        if q:
            qs = qs.filter(
                Q(lead__name__icontains=q)
                | Q(lead__email__icontains=q)
                | Q(lead__phone__icontains=q)
                | Q(last_message_preview__icontains=q)
            )
        # Filtro "minha caixa"
        if self.request.GET.get("mine") == "1":
            qs = qs.filter(assigned_to=self.request.user)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_filter"] = self.request.GET.get("status", "all")
        ctx["search_q"] = self.request.GET.get("q", "")
        ctx["mine_filter"] = self.request.GET.get("mine") == "1"
        # Contadores rápidos para o header
        qs_all = Conversation.objects.filter(empresa=self.request.empresa)
        ctx["count_open"] = qs_all.filter(status=Conversation.Status.OPEN).count()
        ctx["count_in_progress"] = qs_all.filter(status=Conversation.Status.IN_PROGRESS).count()
        ctx["count_unread"] = qs_all.exclude(unread_count=0).count()
        # Active = pega do path (se houver pk em kwargs ou query string)
        active_pk = self.kwargs.get("pk") or self.request.GET.get("active")
        if active_pk:
            try:
                ctx["active_conversation"] = qs_all.get(pk=int(active_pk))
            except (Conversation.DoesNotExist, ValueError, TypeError):
                ctx["active_conversation"] = None
        else:
            ctx["active_conversation"] = None
        return ctx


class ConversationDetailView(EmpresaMixin, DetailView):
    """Thread + composer + painel lateral (renderizado dentro do shell da inbox)."""

    model = Conversation
    template_name = "communications/inbox.html"
    context_object_name = "active_conversation"

    def get_queryset(self):
        return (
            Conversation.objects
            .filter(empresa=self.request.empresa)
            .select_related("lead", "lead__pipeline_stage", "contato", "assigned_to")
        )

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        # Marca como lidas ao abrir
        self.object.mark_read()
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Renderiza shell completo: lista + thread + painel
        conv = self.object
        # Lista (mesma query da InboxView)
        qs_list = (
            Conversation.objects
            .filter(empresa=self.request.empresa)
            .select_related("lead", "contato", "assigned_to")
            .order_by("-last_message_at", "-created_at")[:100]
        )
        ctx["conversations"] = qs_list
        ctx["thread_messages"] = (
            conv.messages.select_related("sender_user").order_by("created_at")
        )
        ctx["send_form"] = SendMessageForm()
        ctx["quick_action_form"] = QuickActionForm()
        # Pipeline stages do tenant para o select de "mover de etapa"
        from apps.crm.models import PipelineStage
        ctx["pipeline_stages"] = (
            PipelineStage.objects
            .filter(pipeline__empresa=self.request.empresa)
            .select_related("pipeline")
            .order_by("pipeline__name", "order")
        )
        # Usuários do tenant para atribuição
        from apps.accounts.models import Membership
        ctx["assignable_users"] = [
            m.user for m in Membership.objects.filter(
                empresa=self.request.empresa, is_active=True,
            ).select_related("user")
        ]
        # Headers/counters
        ctx["status_filter"] = "all"
        ctx["search_q"] = ""
        ctx["mine_filter"] = False
        ctx["count_open"] = Conversation.objects.filter(
            empresa=self.request.empresa, status=Conversation.Status.OPEN,
        ).count()
        ctx["count_in_progress"] = Conversation.objects.filter(
            empresa=self.request.empresa, status=Conversation.Status.IN_PROGRESS,
        ).count()
        ctx["count_unread"] = Conversation.objects.filter(
            empresa=self.request.empresa,
        ).exclude(unread_count=0).count()
        return ctx


class SendMessageView(EmpresaMixin, View):
    """POST: envia mensagem na conversa. Retorna partial do thread (HTMX)."""

    http_method_names = ["post"]

    def post(self, request, pk):
        conv = get_object_or_404(
            Conversation, pk=pk, empresa=request.empresa,
        )
        form = SendMessageForm(request.POST)
        if not form.is_valid():
            return JsonResponse(
                {"error": "invalid", "fields": form.errors}, status=400,
            )
        channel = form.cleaned_data["channel"]
        content = form.cleaned_data["content"]
        if channel == ConversationMessage.Channel.WHATSAPP:
            msg = send_whatsapp(conv, content, sender_user=request.user)
        elif channel == ConversationMessage.Channel.EMAIL:
            subject = form.cleaned_data.get("subject") or f"Mensagem de {request.empresa.name}"
            msg = send_email(conv, subject, content, sender_user=request.user)
        elif channel == ConversationMessage.Channel.INTERNAL_NOTE:
            msg = add_internal_note(conv, content, sender_user=request.user)
        else:
            return JsonResponse({"error": "unsupported_channel"}, status=400)

        if msg.delivery_status == ConversationMessage.DeliveryStatus.FAILED:
            django_messages.warning(
                request, f"Envio falhou: {msg.error_message or 'erro desconhecido'}",
            )
        else:
            django_messages.success(request, "Mensagem enviada.")

        # Re-renderiza thread completo
        if request.htmx:
            conv.refresh_from_db()
            html = render_to_string(
                "communications/partials/_thread.html",
                {
                    "active_conversation": conv,
                    "thread_messages": conv.messages.select_related("sender_user").order_by("created_at"),
                    "send_form": SendMessageForm(),
                },
                request=request,
            )
            return HttpResponse(html)
        return redirect("communications:detail", pk=conv.pk)


class ChangeStatusView(EmpresaMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        conv = get_object_or_404(
            Conversation, pk=pk, empresa=request.empresa,
        )
        new_status = request.POST.get("status", "").strip()
        if new_status not in dict(Conversation.Status.choices):
            return JsonResponse({"error": "invalid_status"}, status=400)
        conv.status = new_status
        conv.save(update_fields=["status", "updated_at"])
        django_messages.success(request, f"Status atualizado para {conv.get_status_display()}.")
        return redirect("communications:detail", pk=conv.pk)


class AssignView(EmpresaMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        conv = get_object_or_404(
            Conversation, pk=pk, empresa=request.empresa,
        )
        user_id = request.POST.get("user_id", "").strip()
        if not user_id or user_id == "0":
            conv.assigned_to = None
            msg = "Conversa desatribuída."
        else:
            from apps.accounts.models import Membership, User
            try:
                user = User.objects.get(pk=int(user_id))
                # Valida que user pertence à mesma empresa
                if not Membership.objects.filter(user=user, empresa=request.empresa, is_active=True).exists():
                    return JsonResponse({"error": "user_not_member"}, status=400)
                conv.assigned_to = user
                msg = f"Conversa atribuída para {user.full_name or user.email}."
            except (ValueError, User.DoesNotExist):
                return JsonResponse({"error": "user_not_found"}, status=400)
        # Quando atribui, move para IN_PROGRESS automaticamente
        if conv.assigned_to and conv.status == Conversation.Status.OPEN:
            conv.status = Conversation.Status.IN_PROGRESS
        conv.save(update_fields=["assigned_to", "status", "updated_at"])
        django_messages.success(request, msg)
        return redirect("communications:detail", pk=conv.pk)


class QuickActionView(EmpresaMixin, View):
    """Executa ação rápida (mover pipeline, criar opportunity/proposal/contract)."""

    http_method_names = ["post"]

    def post(self, request, pk):
        conv = get_object_or_404(
            Conversation.objects.select_related("lead"),
            pk=pk, empresa=request.empresa,
        )
        action = request.POST.get("action", "").strip()
        lead = conv.lead

        try:
            if action == "move_pipeline":
                from apps.crm.models import PipelineStage
                stage_id = int(request.POST.get("pipeline_stage_id", 0) or 0)
                stage = PipelineStage.objects.select_related("pipeline").get(
                    pk=stage_id, pipeline__empresa=request.empresa,
                )
                lead.pipeline_stage = stage
                lead.save(update_fields=["pipeline_stage", "updated_at"])
                add_internal_note(
                    conv,
                    f"Lead movido para etapa '{stage.name}' do pipeline '{stage.pipeline.name}'.",
                    sender_user=request.user,
                )
                django_messages.success(request, f"Lead movido para '{stage.name}'.")

            elif action == "create_opportunity":
                from apps.crm.models import Opportunity, Pipeline
                pipeline = lead.pipeline_stage.pipeline if lead.pipeline_stage else (
                    Pipeline.objects.filter(empresa=request.empresa, is_default=True).first()
                    or Pipeline.objects.filter(empresa=request.empresa).first()
                )
                if not pipeline:
                    django_messages.error(request, "Nenhum pipeline configurado.")
                    return redirect("communications:detail", pk=conv.pk)
                stage = lead.pipeline_stage or pipeline.stages.order_by("order").first()
                title = (request.POST.get("title") or f"Oportunidade — {lead.name}")[:200]
                value = request.POST.get("value") or 0
                opp = Opportunity.objects.create(
                    empresa=request.empresa, lead=lead,
                    pipeline=pipeline, current_stage=stage,
                    title=title, value=value or 0,
                )
                add_internal_note(
                    conv, f"Oportunidade #{opp.pk} criada a partir desta conversa.",
                    sender_user=request.user,
                )
                django_messages.success(request, f"Oportunidade #{opp.pk} criada.")

            elif action == "create_proposal":
                from apps.proposals.models import Proposal
                title = (request.POST.get("title") or f"Proposta — {lead.name}")[:255]
                value = request.POST.get("value") or 0
                proposal = Proposal.objects.create(
                    empresa=request.empresa, lead=lead, title=title,
                )
                add_internal_note(
                    conv, f"Proposta #{proposal.pk} criada. Edite em /proposals/{proposal.pk}/edit/",
                    sender_user=request.user,
                )
                django_messages.success(request, f"Proposta criada. Edite os detalhes na próxima tela.")
                return redirect("proposals:edit", pk=proposal.pk)

            elif action == "create_contract":
                from apps.contracts.models import Contract
                from decimal import Decimal
                title = (request.POST.get("title") or f"Contrato — {lead.name}")[:255]
                value = Decimal(request.POST.get("value") or "0")
                contract = Contract.objects.create(
                    empresa=request.empresa, lead=lead,
                    title=title, value=value,
                )
                add_internal_note(
                    conv, f"Contrato #{contract.pk} criado. Edite em /contracts/{contract.pk}/edit/",
                    sender_user=request.user,
                )
                django_messages.success(request, f"Contrato criado. Edite os detalhes na próxima tela.")
                return redirect("contracts:edit", pk=contract.pk)

            else:
                django_messages.error(request, f"Ação desconhecida: {action}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Erro em quick action %s (conv=%s)", action, conv.pk)
            django_messages.error(request, f"Falha na ação: {exc}")

        return redirect("communications:detail", pk=conv.pk)


class MarkReadView(EmpresaMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        conv = get_object_or_404(Conversation, pk=pk, empresa=request.empresa)
        conv.mark_read()
        if request.htmx:
            return HttpResponse(status=204)
        return redirect("communications:detail", pk=conv.pk)
