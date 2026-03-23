from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.core.mixins import EmpresaMixin, HtmxResponseMixin
from apps.proposals.forms import ProposalForm, ProposalItemForm
from apps.proposals.models import Proposal, ProposalItem


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
        if lead_id:
            from apps.crm.models import Lead

            if Lead.objects.filter(pk=lead_id, empresa=self.request.empresa).exists():
                initial["lead"] = lead_id
        if opportunity_id:
            from apps.crm.models import Opportunity

            if Opportunity.objects.filter(pk=opportunity_id, empresa=self.request.empresa).exists():
                initial["opportunity"] = opportunity_id
        return initial

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
    """Altera o status da proposta (enviar, aceitar, rejeitar)."""

    def post(self, request, pk):
        proposal = get_object_or_404(
            Proposal, pk=pk, empresa=request.empresa
        )
        new_status = request.POST.get("status")
        now = timezone.now()

        valid_transitions = {
            Proposal.Status.DRAFT: [Proposal.Status.SENT],
            Proposal.Status.SENT: [
                Proposal.Status.VIEWED,
                Proposal.Status.ACCEPTED,
                Proposal.Status.REJECTED,
                Proposal.Status.EXPIRED,
            ],
            Proposal.Status.VIEWED: [
                Proposal.Status.ACCEPTED,
                Proposal.Status.REJECTED,
                Proposal.Status.EXPIRED,
            ],
        }

        allowed = valid_transitions.get(proposal.status, [])
        if new_status in allowed:
            proposal.status = new_status
            if new_status == Proposal.Status.SENT:
                proposal.sent_at = now
            elif new_status == Proposal.Status.ACCEPTED:
                proposal.accepted_at = now
            elif new_status == Proposal.Status.REJECTED:
                proposal.rejected_at = now
            proposal.save()

        if request.htmx:
            html = render_to_string(
                "proposals/partials/_proposal_status.html",
                {"proposal": proposal},
                request=request,
            )
            return HttpResponse(html)
        return redirect(proposal.get_absolute_url())
