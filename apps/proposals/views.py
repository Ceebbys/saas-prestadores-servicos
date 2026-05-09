import json

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.core.mixins import EmpresaMixin, HtmxResponseMixin
from apps.proposals.forms import (
    ProposalForm,
    ProposalItemForm,
    ProposalTemplateItemForm,
)
from apps.proposals.models import (
    Proposal,
    ProposalItem,
    ProposalTemplate,
    ProposalTemplateItem,
)
from apps.proposals.services.render import (
    build_proposal_context,
    render_proposal_docx,
    render_proposal_pdf,
)


class ProposalListView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = Proposal
    template_name = "proposals/proposal_list.html"
    partial_template_name = "proposals/partials/_proposal_table.html"
    context_object_name = "proposals"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("lead", "opportunity")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(number__icontains=q))
        status = self.request.GET.get("status", "").strip()
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = Proposal.Status.choices
        context["current_status"] = self.request.GET.get("status", "")
        context["search_query"] = self.request.GET.get("q", "")
        return context


class ProposalDetailView(EmpresaMixin, DetailView):
    model = Proposal
    template_name = "proposals/proposal_detail.html"
    context_object_name = "proposal"

    def get_queryset(self):
        return super().get_queryset().select_related(
            "lead", "opportunity", "template"
        ).prefetch_related("items")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["item_form"] = ProposalItemForm()
        return context


def _serialize_templates_for_form(empresa):
    """Serializa templates da empresa para uso no form (Alpine.js)."""
    data = {}
    for tpl in ProposalTemplate.objects.filter(empresa=empresa).prefetch_related(
        "default_items"
    ):
        data[str(tpl.pk)] = {
            "introduction": tpl.introduction or "",
            "terms": tpl.terms or "",
            "payment_method": tpl.default_payment_method or "",
            "is_installment": bool(tpl.default_is_installment),
            "installment_count": tpl.default_installment_count or "",
            "has_items": tpl.default_items.exists(),
        }
    return json.dumps(data)


class ProposalCreateView(EmpresaMixin, CreateView):
    model = Proposal
    form_class = ProposalForm
    template_name = "proposals/proposal_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        lead_id = self.request.GET.get("lead_id")
        opportunity_id = self.request.GET.get("opportunity_id")
        servico_id = self.request.GET.get("servico_id")

        if lead_id:
            from apps.crm.models import Lead

            lead = Lead.objects.filter(
                pk=lead_id, empresa=self.request.empresa
            ).select_related("servico").first()
            if lead:
                initial["lead"] = lead_id
                # Se o lead tem serviço vinculado e nenhum servico_id
                # explícito veio na URL, herda dele.
                if not servico_id and lead.servico_id:
                    servico_id = str(lead.servico_id)

        if opportunity_id:
            from apps.crm.models import Opportunity

            if Opportunity.objects.filter(pk=opportunity_id, empresa=self.request.empresa).exists():
                initial["opportunity"] = opportunity_id

        if servico_id:
            from apps.operations.models import ServiceType

            servico = ServiceType.objects.filter(
                pk=servico_id, empresa=self.request.empresa,
            ).select_related(
                "default_proposal_template",
            ).first()
            if servico:
                initial["servico"] = servico.pk
                # Pré-preenche valor padrão, descrição, prazo
                if servico.default_description and "introduction" not in initial:
                    initial["introduction"] = servico.default_description
                if servico.default_proposal_template_id and "template" not in initial:
                    initial["template"] = servico.default_proposal_template_id
                if servico.default_prazo_dias and "valid_until" not in initial:
                    from datetime import timedelta
                    initial["valid_until"] = (
                        timezone.now().date()
                        + timedelta(days=servico.default_prazo_dias)
                    )
                # Título padrão se ainda não tiver
                if "title" not in initial:
                    initial["title"] = servico.name
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["templates_data"] = _serialize_templates_for_form(
            self.request.empresa
        )
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Proposta criada com sucesso.")
        return response

    def get_success_url(self):
        return self.object.get_absolute_url()


class ProposalUpdateView(EmpresaMixin, UpdateView):
    model = Proposal
    form_class = ProposalForm
    template_name = "proposals/proposal_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["templates_data"] = _serialize_templates_for_form(
            self.request.empresa
        )
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Proposta atualizada com sucesso.")
        return response

    def get_success_url(self):
        return self.object.get_absolute_url()


class ProposalItemAddView(EmpresaMixin, View):
    """Adiciona um item à proposta via HTMX."""

    def post(self, request, proposal_pk):
        proposal = get_object_or_404(
            Proposal, pk=proposal_pk, empresa=request.empresa
        )
        form = ProposalItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.proposal = proposal
            max_order = proposal.items.order_by("-order").values_list(
                "order", flat=True
            ).first()
            item.order = (max_order or 0) + 1
            item.save()
            proposal.recalculate_totals()

        html = render_to_string(
            "proposals/partials/_proposal_items.html",
            {
                "proposal": proposal,
                "items": proposal.items.all(),
                "item_form": ProposalItemForm(),
            },
            request=request,
        )
        return HttpResponse(html)


class ProposalItemEditView(EmpresaMixin, View):
    """Edita um item da proposta via HTMX."""

    def get(self, request, proposal_pk, item_pk):
        proposal = get_object_or_404(
            Proposal, pk=proposal_pk, empresa=request.empresa
        )
        item = get_object_or_404(ProposalItem, pk=item_pk, proposal=proposal)
        form = ProposalItemForm(instance=item)
        html = render_to_string(
            "proposals/partials/_proposal_item_edit.html",
            {"form": form, "proposal": proposal, "item": item},
            request=request,
        )
        return HttpResponse(html)

    def post(self, request, proposal_pk, item_pk):
        proposal = get_object_or_404(
            Proposal, pk=proposal_pk, empresa=request.empresa
        )
        item = get_object_or_404(ProposalItem, pk=item_pk, proposal=proposal)
        form = ProposalItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            proposal.recalculate_totals()

        html = render_to_string(
            "proposals/partials/_proposal_items.html",
            {
                "proposal": proposal,
                "items": proposal.items.all(),
                "item_form": ProposalItemForm(),
            },
            request=request,
        )
        return HttpResponse(html)


class ProposalItemDeleteView(EmpresaMixin, View):
    """Remove um item da proposta via HTMX."""

    def post(self, request, proposal_pk, item_pk):
        proposal = get_object_or_404(
            Proposal, pk=proposal_pk, empresa=request.empresa
        )
        item = get_object_or_404(ProposalItem, pk=item_pk, proposal=proposal)
        item.delete()
        proposal.recalculate_totals()

        html = render_to_string(
            "proposals/partials/_proposal_items.html",
            {
                "proposal": proposal,
                "items": proposal.items.all(),
                "item_form": ProposalItemForm(),
            },
            request=request,
        )
        return HttpResponse(html)


class ProposalStatusView(EmpresaMixin, View):
    """Altera o status da proposta. Permite todas as transições úteis,
    incluindo desfazer (qualquer estado → DRAFT)."""

    # Cada estado pode transicionar para qualquer outro a partir do conjunto
    # abaixo. CANCELLED é alcançável de qualquer um. DRAFT é destino "desfazer"
    # universal.
    VALID_TRANSITIONS = {
        Proposal.Status.DRAFT: [
            Proposal.Status.SENT, Proposal.Status.CANCELLED,
        ],
        Proposal.Status.SENT: [
            Proposal.Status.VIEWED, Proposal.Status.ACCEPTED,
            Proposal.Status.REJECTED, Proposal.Status.EXPIRED,
            Proposal.Status.CANCELLED, Proposal.Status.DRAFT,
        ],
        Proposal.Status.VIEWED: [
            Proposal.Status.ACCEPTED, Proposal.Status.REJECTED,
            Proposal.Status.EXPIRED, Proposal.Status.CANCELLED,
            Proposal.Status.DRAFT,
        ],
        Proposal.Status.ACCEPTED: [
            Proposal.Status.DRAFT, Proposal.Status.REJECTED,
            Proposal.Status.CANCELLED,
        ],
        Proposal.Status.REJECTED: [
            Proposal.Status.DRAFT, Proposal.Status.ACCEPTED,
            Proposal.Status.CANCELLED,
        ],
        Proposal.Status.EXPIRED: [
            Proposal.Status.DRAFT, Proposal.Status.SENT,
            Proposal.Status.CANCELLED,
        ],
        Proposal.Status.CANCELLED: [Proposal.Status.DRAFT],
    }

    def post(self, request, pk):
        from apps.proposals.models import ProposalStatusHistory

        proposal = get_object_or_404(
            Proposal, pk=pk, empresa=request.empresa
        )
        new_status = request.POST.get("status")
        note = (request.POST.get("note") or "").strip()
        now = timezone.now()

        old_status = proposal.status
        allowed = self.VALID_TRANSITIONS.get(old_status, [])

        if new_status not in allowed:
            messages.error(
                request,
                f"Transição não permitida: {old_status} → {new_status}",
            )
            if request.htmx:
                html = render_to_string(
                    "proposals/partials/_proposal_status.html",
                    {"proposal": proposal},
                    request=request,
                )
                return HttpResponse(html)
            return redirect(proposal.get_absolute_url())

        proposal.status = new_status
        if new_status == Proposal.Status.SENT:
            proposal.sent_at = now
        elif new_status == Proposal.Status.ACCEPTED:
            proposal.accepted_at = now
        elif new_status == Proposal.Status.REJECTED:
            proposal.rejected_at = now
        elif new_status == Proposal.Status.DRAFT and old_status == Proposal.Status.ACCEPTED:
            # Desfazendo aceite — limpa accepted_at e avisa sobre financeiro
            proposal.accepted_at = None
            messages.warning(
                request,
                "Status desfeito. Lançamentos financeiros gerados anteriormente "
                "permanecem — reverta manualmente se necessário.",
            )
        elif new_status == Proposal.Status.DRAFT and old_status == Proposal.Status.REJECTED:
            proposal.rejected_at = None
        proposal.save()

        # Histórico de auditoria
        ProposalStatusHistory.objects.create(
            proposal=proposal,
            from_status=old_status,
            to_status=new_status,
            changed_by=request.user if request.user.is_authenticated else None,
            note=note,
        )

        # Integração com financeiro: gera lançamentos ao aceitar
        if new_status == Proposal.Status.ACCEPTED:
            from apps.finance.services import (
                generate_entries_from_proposal,
            )

            try:
                entries = generate_entries_from_proposal(proposal)
                if entries:
                    already = any(
                        e.created_at < now for e in entries
                    )
                    if already:
                        messages.info(
                            request,
                            "Lançamentos financeiros já existentes "
                            "foram mantidos.",
                        )
                    else:
                        messages.success(
                            request,
                            f"{len(entries)} lançamento(s) financeiro(s) "
                            f"criado(s) a partir da proposta.",
                        )
            except Exception as exc:  # noqa: BLE001
                messages.warning(
                    request,
                    f"Proposta aceita, mas houve erro ao gerar "
                    f"financeiro: {exc}",
                )

        if request.htmx:
            html = render_to_string(
                "proposals/partials/_proposal_status.html",
                {"proposal": proposal},
                request=request,
            )
            return HttpResponse(html)
        return redirect(proposal.get_absolute_url())


class ProposalDeleteView(EmpresaMixin, View):
    """Exclui proposta com confirmação. Hard delete + log de auditoria.

    GET retorna form de confirmação (modal HTMX).
    POST executa a exclusão após confirmação dupla.
    """

    def get(self, request, pk):
        proposal = get_object_or_404(
            Proposal, pk=pk, empresa=request.empresa
        )
        html = render_to_string(
            "proposals/partials/_delete_confirm.html",
            {"proposal": proposal},
            request=request,
        )
        return HttpResponse(html)

    def post(self, request, pk):
        from apps.automation.models import AutomationLog

        proposal = get_object_or_404(
            Proposal, pk=pk, empresa=request.empresa
        )
        # Snapshot antes de excluir (mantido em AutomationLog para auditoria
        # mesmo que a proposta seja restaurada depois — registra a ação)
        snapshot = {
            "number": proposal.number,
            "title": proposal.title,
            "status": proposal.status,
            "total": str(proposal.total),
            "lead_id": proposal.lead_id,
            "lead_name": proposal.lead.name if proposal.lead else None,
            "deleted_by_user_id": request.user.pk if request.user.is_authenticated else None,
            "deleted_at": timezone.now().isoformat(),
            "soft": True,
        }
        AutomationLog.objects.create(
            empresa=request.empresa,
            action=AutomationLog.Action.PROPOSAL_DELETED,
            entity_type=AutomationLog.EntityType.PROPOSAL,
            entity_id=proposal.pk,
            status=AutomationLog.Status.SUCCESS,
            metadata={"event": "proposal_deleted", **snapshot},
        )
        number = proposal.number
        proposal.delete()  # soft-delete: seta deleted_at
        messages.success(
            request,
            f"Proposta {number} movida para a lixeira. "
            f"Você pode restaurá-la em /proposals/trash/.",
        )
        return redirect("proposals:list")


class ProposalTrashView(EmpresaMixin, ListView):
    """Lixeira: lista propostas soft-deleted da empresa."""

    template_name = "proposals/proposal_trash.html"
    context_object_name = "proposals"
    paginate_by = 30

    def get_queryset(self):
        return (
            Proposal.all_objects.filter(
                empresa=self.request.empresa,
                deleted_at__isnull=False,
            )
            .select_related("lead")
            .order_by("-deleted_at")
        )


class ProposalRestoreView(EmpresaMixin, View):
    """Restaura uma proposta soft-deleted."""

    def post(self, request, pk):
        from apps.automation.models import AutomationLog

        proposal = get_object_or_404(
            Proposal.all_objects, pk=pk,
            empresa=request.empresa, deleted_at__isnull=False,
        )
        proposal.restore()
        AutomationLog.objects.create(
            empresa=request.empresa,
            action=AutomationLog.Action.PROPOSAL_DELETED,  # reusa enum
            entity_type=AutomationLog.EntityType.PROPOSAL,
            entity_id=proposal.pk,
            status=AutomationLog.Status.SUCCESS,
            metadata={
                "event": "proposal_restored",
                "number": proposal.number,
                "restored_by_user_id": request.user.pk,
                "restored_at": timezone.now().isoformat(),
            },
        )
        messages.success(request, f"Proposta {proposal.number} restaurada.")
        return redirect("proposals:trash")


class ProposalHardDeleteView(EmpresaMixin, View):
    """Exclusão definitiva (apenas a partir da lixeira)."""

    def post(self, request, pk):
        from apps.automation.models import AutomationLog

        proposal = get_object_or_404(
            Proposal.all_objects, pk=pk,
            empresa=request.empresa, deleted_at__isnull=False,
        )
        AutomationLog.objects.create(
            empresa=request.empresa,
            action=AutomationLog.Action.PROPOSAL_DELETED,
            entity_type=AutomationLog.EntityType.PROPOSAL,
            entity_id=proposal.pk,
            status=AutomationLog.Status.SUCCESS,
            metadata={
                "event": "proposal_hard_deleted",
                "number": proposal.number,
                "hard_deleted_by_user_id": request.user.pk,
            },
        )
        number = proposal.number
        proposal.hard_delete()
        messages.success(
            request, f"Proposta {number} excluída definitivamente.",
        )
        return redirect("proposals:trash")


# ---------------------------------------------------------------------------
# ProposalTemplate — endpoints auxiliares (HTMX)
# CRUD completo vive em apps/settings_app para manter ponto único de
# configuração. Aqui ficam apenas os endpoints que operam sobre itens
# padrão e a aplicação desses itens em propostas.
# ---------------------------------------------------------------------------


class TemplateItemAddView(EmpresaMixin, View):
    """Adiciona um item padrão ao template via HTMX."""

    def post(self, request, template_pk):
        template = get_object_or_404(
            ProposalTemplate, pk=template_pk, empresa=request.empresa
        )
        form = ProposalTemplateItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.template = template
            max_order = (
                template.default_items.order_by("-order")
                .values_list("order", flat=True)
                .first()
            )
            item.order = (max_order or 0) + 1
            item.save()

        html = render_to_string(
            "proposals/partials/_template_items.html",
            {
                "template": template,
                "template_items": template.default_items.all(),
                "item_form": ProposalTemplateItemForm(),
            },
            request=request,
        )
        return HttpResponse(html)


class TemplateItemDeleteView(EmpresaMixin, View):
    """Remove um item padrão do template via HTMX."""

    def post(self, request, template_pk, item_pk):
        template = get_object_or_404(
            ProposalTemplate, pk=template_pk, empresa=request.empresa
        )
        item = get_object_or_404(
            ProposalTemplateItem, pk=item_pk, template=template
        )
        item.delete()

        html = render_to_string(
            "proposals/partials/_template_items.html",
            {
                "template": template,
                "template_items": template.default_items.all(),
                "item_form": ProposalTemplateItemForm(),
            },
            request=request,
        )
        return HttpResponse(html)


class ProposalPreviewView(EmpresaMixin, View):
    """Renderiza preview HTML da proposta (mesmo template do PDF)."""

    def get(self, request, pk):
        proposal = get_object_or_404(
            Proposal.objects.select_related("lead", "lead__contato", "template", "empresa")
            .prefetch_related("items"),
            pk=pk, empresa=request.empresa,
        )
        ctx = build_proposal_context(proposal, request=request)
        ctx["preview_mode"] = True
        return render(request, "proposals/render/proposal_print.html", ctx)


class ProposalPDFView(EmpresaMixin, View):
    """Gera e devolve o PDF da proposta."""

    def get(self, request, pk):
        proposal = get_object_or_404(
            Proposal.objects.select_related("lead", "lead__contato", "template", "empresa")
            .prefetch_related("items"),
            pk=pk, empresa=request.empresa,
        )
        try:
            pdf_bytes = render_proposal_pdf(proposal, request=request)
        except Exception as exc:  # noqa: BLE001
            messages.error(
                request,
                f"Não foi possível gerar PDF: {exc}. Verifique se WeasyPrint está instalado.",
            )
            return redirect(proposal.get_absolute_url())
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="Proposta_{proposal.number}.pdf"'
        )
        return response


class ProposalDOCXView(EmpresaMixin, View):
    """Gera e devolve o DOCX (estruturado, sem rich formatting)."""

    DOCX_CT = (
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document"
    )

    def get(self, request, pk):
        proposal = get_object_or_404(
            Proposal.objects.select_related("lead", "lead__contato", "template", "empresa")
            .prefetch_related("items"),
            pk=pk, empresa=request.empresa,
        )
        try:
            docx_bytes = render_proposal_docx(proposal)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"Não foi possível gerar DOCX: {exc}")
            return redirect(proposal.get_absolute_url())
        response = HttpResponse(docx_bytes, content_type=self.DOCX_CT)
        response["Content-Disposition"] = (
            f'attachment; filename="Proposta_{proposal.number}.docx"'
        )
        return response


class ProposalSendEmailView(EmpresaMixin, View):
    """Envia proposta por e-mail (form + service)."""

    def get(self, request, pk):
        proposal = get_object_or_404(
            Proposal.objects.select_related("lead", "lead__contato"),
            pk=pk, empresa=request.empresa,
        )
        contato = getattr(proposal.lead, "contato", None) if proposal.lead else None
        default_email = (contato.email if contato else "") or proposal.lead.email
        ctx = {
            "proposal": proposal,
            "default_email": default_email or "",
            "default_subject": f"Proposta {proposal.number} — {proposal.empresa.name}",
        }
        html = render_to_string(
            "proposals/partials/_send_email_form.html", ctx, request=request,
        )
        return HttpResponse(html)

    def post(self, request, pk):
        from apps.proposals.services.email import send_proposal_email

        proposal = get_object_or_404(
            Proposal, pk=pk, empresa=request.empresa,
        )
        to_email = (request.POST.get("to_email") or "").strip()
        subject = (request.POST.get("subject") or "").strip() or None
        message = request.POST.get("message") or ""
        ok, err = send_proposal_email(
            proposal, to_email=to_email, subject=subject,
            message=message, request=request,
        )
        if ok:
            messages.success(request, f"Proposta enviada para {to_email}.")
        else:
            messages.error(request, f"Falha ao enviar e-mail: {err}")
        return redirect(proposal.get_absolute_url())


class ProposalSendWhatsAppView(EmpresaMixin, View):
    """Envia proposta por WhatsApp (anexo PDF + fallback link)."""

    def get(self, request, pk):
        proposal = get_object_or_404(
            Proposal.objects.select_related("lead", "lead__contato"),
            pk=pk, empresa=request.empresa,
        )
        contato = getattr(proposal.lead, "contato", None) if proposal.lead else None
        default_phone = ""
        if contato:
            default_phone = contato.whatsapp or contato.phone or ""
        elif proposal.lead and proposal.lead.phone:
            default_phone = proposal.lead.phone
        ctx = {
            "proposal": proposal,
            "default_phone": default_phone,
            "default_message": (
                f"Olá! Segue a proposta {proposal.number}."
            ),
        }
        html = render_to_string(
            "proposals/partials/_send_whatsapp_form.html", ctx, request=request,
        )
        return HttpResponse(html)

    def post(self, request, pk):
        from apps.proposals.services.whatsapp import send_proposal_whatsapp

        proposal = get_object_or_404(
            Proposal, pk=pk, empresa=request.empresa,
        )
        to_phone = (request.POST.get("to_phone") or "").strip()
        message = request.POST.get("message") or ""
        ok, mode, msg = send_proposal_whatsapp(
            proposal, to_phone=to_phone, message=message, request=request,
        )
        if ok and mode == "attachment":
            messages.success(request, msg)
        elif ok and mode == "link":
            messages.warning(request, msg)
        else:
            messages.error(request, msg)
        return redirect(proposal.get_absolute_url())


class ProposalPublicView(View):
    """Visualização pública da proposta via token UUID — sem autenticação.

    Marca `viewed_at` na primeira visualização e transita DRAFT/SENT → VIEWED.
    Sem CSRF, sem EmpresaMixin — endpoint pensado para o cliente final.
    """

    def get(self, request, token):
        proposal = get_object_or_404(
            Proposal.objects.select_related("lead", "lead__contato", "template", "empresa")
            .prefetch_related("items"),
            public_token=token,
        )
        # Marca visualização e atualiza status na primeira vez
        if proposal.viewed_at is None:
            proposal.viewed_at = timezone.now()
            update_fields = ["viewed_at", "updated_at"]
            if proposal.status in (Proposal.Status.DRAFT, Proposal.Status.SENT):
                proposal.status = Proposal.Status.VIEWED
                update_fields.append("status")
            proposal.save(update_fields=update_fields)

        from apps.proposals.services.render import build_proposal_context

        ctx = build_proposal_context(proposal, request=request)
        ctx["preview_mode"] = False
        ctx["public_view"] = True
        return render(request, "proposals/render/proposal_print.html", ctx)


class ProposalApplyTemplateItemsView(EmpresaMixin, View):
    """Carrega itens padrão do template vinculado em uma proposta existente."""

    def post(self, request, pk):
        proposal = get_object_or_404(
            Proposal, pk=pk, empresa=request.empresa
        )
        if not proposal.template_id:
            messages.warning(request, "Proposta não tem template vinculado.")
            return redirect(proposal.get_absolute_url())

        default_items = proposal.template.default_items.all()
        if not default_items.exists():
            messages.info(request, "Template não possui itens padrão.")
            return redirect(proposal.get_absolute_url())

        # Parte da ordem atual para não colidir com itens existentes
        max_order = (
            proposal.items.order_by("-order")
            .values_list("order", flat=True)
            .first()
            or 0
        )
        created = 0
        for idx, tpl_item in enumerate(default_items, start=1):
            ProposalItem.objects.create(
                proposal=proposal,
                description=tpl_item.description,
                details=tpl_item.details,
                quantity=tpl_item.quantity,
                unit=tpl_item.unit,
                unit_price=tpl_item.unit_price,
                order=max_order + idx,
            )
            created += 1
        proposal.recalculate_totals()
        messages.success(
            request, f"{created} item(ns) carregado(s) do template."
        )

        if request.htmx:
            html = render_to_string(
                "proposals/partials/_proposal_items.html",
                {
                    "proposal": proposal,
                    "items": proposal.items.all(),
                    "item_form": ProposalItemForm(),
                },
                request=request,
            )
            return HttpResponse(html)
        return redirect(proposal.get_absolute_url())
