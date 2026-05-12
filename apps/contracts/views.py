from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

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
        # Herda termos da proposta como conteúdo inicial do contrato
        if proposal.terms:
            initial["content"] = proposal.terms
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


class ContractDeleteView(EmpresaMixin, DeleteView):
    model = Contract
    success_url = reverse_lazy("contracts:list")
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        messages.success(request, "Contrato excluído com sucesso.")
        return self.delete(request, *args, **kwargs)


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
