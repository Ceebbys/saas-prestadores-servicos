from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.core.mixins import EmpresaMixin, HtmxResponseMixin
from apps.contracts.forms import ContractForm
from apps.contracts.models import Contract
from apps.proposals.models import Proposal


class ContractListView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = Contract
    template_name = "contracts/contract_list.html"
    partial_template_name = "contracts/partials/_contract_table.html"
    context_object_name = "contracts"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("lead", "proposal")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(number__icontains=q))
        status = self.request.GET.get("status", "").strip()
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = Contract.Status.choices
        context["current_status"] = self.request.GET.get("status", "")
        context["search_query"] = self.request.GET.get("q", "")
        return context


class ContractDetailView(EmpresaMixin, DetailView):
    model = Contract
    template_name = "contracts/contract_detail.html"
    context_object_name = "contract"

    def get_queryset(self):
        return super().get_queryset().select_related("lead", "proposal", "template")


class ContractCreateView(EmpresaMixin, CreateView):
    model = Contract
    form_class = ContractForm
    template_name = "contracts/contract_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        lead_id = self.request.GET.get("lead_id")
        if lead_id:
            from apps.crm.models import Lead

            if Lead.objects.filter(pk=lead_id, empresa=self.request.empresa).exists():
                initial["lead"] = lead_id
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Contrato criado com sucesso.")
        return response

    def get_success_url(self):
        return self.object.get_absolute_url()


class ContractFromProposalView(EmpresaMixin, CreateView):
    """Cria um contrato a partir de uma proposta existente."""

    model = Contract
    form_class = ContractForm
    template_name = "contracts/contract_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        proposal = get_object_or_404(
            Proposal,
            pk=self.kwargs["proposal_pk"],
            empresa=self.request.empresa,
        )
        initial["proposal"] = proposal.pk
        initial["lead"] = proposal.lead_id
        initial["title"] = f"Contrato - {proposal.title}"
        initial["value"] = proposal.total
        # RV05-H — popula `body` (campo rich novo) E `terms` (rich) a partir
        # da proposta. Antes populava apenas `content` legado, deixando o
        # body vazio e o contrato dependendo do dual-read no render.
        # Sanitização é redundante (Proposal.body/terms já são sanitizados
        # no ProposalForm), mas mantém defense-in-depth.
        from apps.core.document_render.sanitizer import sanitize_rich_html
        if proposal.body:
            initial["body"] = sanitize_rich_html(proposal.body)
        if proposal.terms:
            initial["terms"] = sanitize_rich_html(proposal.terms)
        if proposal.introduction:
            initial["introduction"] = sanitize_rich_html(proposal.introduction)
        initial["notes"] = self._build_notes(proposal)
        return initial

    def _build_notes(self, proposal):
        """Consolida informações de pagamento da proposta em notas do contrato."""
        lines = [f"Contrato referente à proposta {proposal.number}."]
        if proposal.payment_method:
            lines.append(
                f"Forma de pagamento: {proposal.get_payment_method_display()}"
            )
        if proposal.is_installment and proposal.installment_count:
            lines.append(
                f"Parcelamento: {proposal.installment_count}x"
            )
        return "\n".join(lines)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Contrato criado a partir da proposta.")
        return response

    def get_success_url(self):
        return self.object.get_absolute_url()


class ContractUpdateView(EmpresaMixin, UpdateView):
    model = Contract
    form_class = ContractForm
    template_name = "contracts/contract_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Contrato atualizado com sucesso.")
        return response

    def get_success_url(self):
        return self.object.get_absolute_url()


class ContractDeleteView(EmpresaMixin, View):
    """RV08 (1.1) — Exclui contrato (soft-delete) com confirmação.

    Só permite excluir contratos em **Rascunho** ou **Cancelado** (proteção
    contra exclusão acidental de contratos ativos/assinados). Espelha a UX de
    `ProposalDeleteView`:

    - GET  → modal de confirmação (HTMX) com cascata opcional de lançamentos.
    - POST → valida status, cascata opcional de financeiros pendentes,
      `AutomationLog` de auditoria e soft-delete (restaurável na lixeira).
    """

    ALLOWED_STATUSES = {Contract.Status.DRAFT, Contract.Status.CANCELLED}

    def get(self, request, pk):
        contract = get_object_or_404(Contract, pk=pk, empresa=request.empresa)
        pending_entries = contract.financial_entries.filter(
            status__in=("pending", "overdue"),
        )
        paid_entries_count = contract.financial_entries.filter(
            status="paid",
        ).count()
        html = render_to_string(
            "contracts/partials/_delete_confirm.html",
            {
                "contract": contract,
                "can_delete": contract.status in self.ALLOWED_STATUSES,
                "pending_entries": pending_entries,
                "pending_entries_count": pending_entries.count(),
                "paid_entries_count": paid_entries_count,
            },
            request=request,
        )
        return HttpResponse(html)

    def post(self, request, pk):
        from apps.automation.models import AutomationLog

        contract = get_object_or_404(Contract, pk=pk, empresa=request.empresa)
        if contract.status not in self.ALLOWED_STATUSES:
            messages.error(
                request,
                "Só é possível excluir contratos em Rascunho ou Cancelado. "
                "Cancele o contrato antes de excluí-lo.",
            )
            return redirect(contract.get_absolute_url())

        # Cascata opcional: exclui também os lançamentos pendentes vinculados.
        delete_entries = request.POST.get("delete_entries") == "1"
        entries_deleted = 0
        if delete_entries:
            deleted_total, _by_model = contract.financial_entries.filter(
                status__in=("pending", "overdue"),
            ).delete()
            entries_deleted = deleted_total

        snapshot = {
            "number": contract.number,
            "title": contract.title,
            "status": contract.status,
            "value": str(contract.value),
            "lead_id": contract.lead_id,
            "lead_name": contract.lead.name if contract.lead_id else None,
            "deleted_by_user_id": (
                request.user.pk if request.user.is_authenticated else None
            ),
            "deleted_at": timezone.now().isoformat(),
            "soft": True,
            "cascaded_entries_deleted": entries_deleted,
        }
        AutomationLog.objects.create(
            empresa=request.empresa,
            action=AutomationLog.Action.CONTRACT_DELETED,
            entity_type=AutomationLog.EntityType.CONTRACT,
            entity_id=contract.pk,
            status=AutomationLog.Status.SUCCESS,
            metadata={"event": "contract_deleted", **snapshot},
        )
        number = contract.number
        contract.delete()  # soft-delete: seta deleted_at
        msg = (
            f"Contrato {number} movido para a lixeira. "
            f"Você pode restaurá-lo em Contratos › Lixeira."
        )
        if entries_deleted:
            msg += (
                f" {entries_deleted} lançamento(s) financeiro(s) pendente(s) "
                f"também foram excluído(s)."
            )
        messages.success(request, msg)
        return redirect("contracts:list")


class ContractTrashView(EmpresaMixin, ListView):
    """RV08 (1.1) — Lixeira: contratos soft-deleted da empresa."""

    template_name = "contracts/contract_trash.html"
    context_object_name = "contracts"
    paginate_by = 30

    def get_queryset(self):
        return (
            Contract.all_objects.filter(
                empresa=self.request.empresa,
                deleted_at__isnull=False,
            )
            .select_related("lead")
            .order_by("-deleted_at")
        )


class ContractRestoreView(EmpresaMixin, View):
    """RV08 (1.1) — Restaura um contrato soft-deleted."""

    def post(self, request, pk):
        from apps.automation.models import AutomationLog

        contract = get_object_or_404(
            Contract.all_objects, pk=pk,
            empresa=request.empresa, deleted_at__isnull=False,
        )
        contract.restore()
        AutomationLog.objects.create(
            empresa=request.empresa,
            action=AutomationLog.Action.CONTRACT_DELETED,  # reusa enum
            entity_type=AutomationLog.EntityType.CONTRACT,
            entity_id=contract.pk,
            status=AutomationLog.Status.SUCCESS,
            metadata={
                "event": "contract_restored",
                "number": contract.number,
                "restored_by_user_id": (
                    request.user.pk if request.user.is_authenticated else None
                ),
                "restored_at": timezone.now().isoformat(),
            },
        )
        messages.success(request, f"Contrato {contract.number} restaurado.")
        return redirect("contracts:trash")


class ContractHardDeleteView(EmpresaMixin, View):
    """RV08 (1.1) — Exclusão definitiva (apenas a partir da lixeira)."""

    def post(self, request, pk):
        from apps.automation.models import AutomationLog

        contract = get_object_or_404(
            Contract.all_objects, pk=pk,
            empresa=request.empresa, deleted_at__isnull=False,
        )
        AutomationLog.objects.create(
            empresa=request.empresa,
            action=AutomationLog.Action.CONTRACT_DELETED,
            entity_type=AutomationLog.EntityType.CONTRACT,
            entity_id=contract.pk,
            status=AutomationLog.Status.SUCCESS,
            metadata={
                "event": "contract_hard_deleted",
                "number": contract.number,
                "hard_deleted_by_user_id": (
                    request.user.pk if request.user.is_authenticated else None
                ),
            },
        )
        number = contract.number
        contract.hard_delete()
        messages.success(request, f"Contrato {number} excluído definitivamente.")
        return redirect("contracts:trash")


class ContractStatusView(EmpresaMixin, View):
    """Altera o status do contrato."""

    def post(self, request, pk):
        contract = get_object_or_404(
            Contract, pk=pk, empresa=request.empresa
        )
        new_status = request.POST.get("status")
        now = timezone.now()

        valid_transitions = {
            Contract.Status.DRAFT: [Contract.Status.SENT],
            Contract.Status.SENT: [
                Contract.Status.SIGNED,
                Contract.Status.CANCELLED,
            ],
            Contract.Status.SIGNED: [
                Contract.Status.ACTIVE,
                Contract.Status.CANCELLED,
            ],
            Contract.Status.ACTIVE: [
                Contract.Status.COMPLETED,
                Contract.Status.CANCELLED,
            ],
        }

        allowed = valid_transitions.get(contract.status, [])
        if new_status in allowed:
            contract.status = new_status
            if new_status == Contract.Status.SIGNED:
                contract.signed_at = now
            # RV05-F — flags lidas pelo signal post_save para atribuir autor.
            contract._status_changed_by = request.user
            contract._status_change_note = request.POST.get("note", "") or ""
            contract.save()

        if request.htmx:
            html = render_to_string(
                "contracts/partials/_contract_status.html",
                {"contract": contract},
                request=request,
            )
            return HttpResponse(html)
        return redirect(contract.get_absolute_url())


# ---------------------------------------------------------------------------
# RV05 #11 — Preview / PDF / DOCX (padronização com Proposal)
# ---------------------------------------------------------------------------


class ContractPreviewView(EmpresaMixin, View):
    """Renderiza preview HTML (mesmo template do PDF)."""

    def get(self, request, pk):
        from django.shortcuts import render
        from apps.contracts.services.render import build_contract_context

        contract = get_object_or_404(
            Contract.objects.select_related("lead", "lead__contato", "template", "empresa"),
            pk=pk, empresa=request.empresa,
        )
        ctx = build_contract_context(contract, request=request)
        ctx["preview_mode"] = True
        return render(request, "contracts/render/contract_print.html", ctx)


class ContractPDFView(EmpresaMixin, View):
    """Gera e devolve PDF do contrato."""

    def get(self, request, pk):
        from apps.contracts.services.render import render_contract_pdf
        import logging

        contract = get_object_or_404(
            Contract.objects.select_related("lead", "lead__contato", "template", "empresa"),
            pk=pk, empresa=request.empresa,
        )
        try:
            pdf_bytes = render_contract_pdf(contract, request=request)
        except ValueError as exc:
            messages.error(request, f"Não foi possível gerar PDF: {exc}")
            return redirect(contract.get_absolute_url())
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception(
                "Falha inesperada ao gerar PDF do contrato %s (%s)",
                contract.pk, contract.number,
            )
            messages.error(
                request,
                "Não foi possível gerar o PDF agora. Tente novamente — se persistir, contate o suporte.",
            )
            return redirect(contract.get_absolute_url())
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="Contrato_{contract.number}.pdf"'
        )
        return response


class ContractDOCXView(EmpresaMixin, View):
    """Gera e devolve DOCX estruturado (limitação: rich vira plain)."""

    DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def get(self, request, pk):
        from apps.contracts.services.render import render_contract_docx

        contract = get_object_or_404(
            Contract.objects.select_related("lead", "lead__contato", "template", "empresa"),
            pk=pk, empresa=request.empresa,
        )
        try:
            docx_bytes = render_contract_docx(contract)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"Não foi possível gerar DOCX: {exc}")
            return redirect(contract.get_absolute_url())
        response = HttpResponse(docx_bytes, content_type=self.DOCX_CT)
        response["Content-Disposition"] = (
            f'attachment; filename="Contrato_{contract.number}.docx"'
        )
        return response
