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
        return initial

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
