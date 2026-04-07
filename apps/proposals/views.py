import json

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
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
        if lead_id:
            from apps.crm.models import Lead

            if Lead.objects.filter(pk=lead_id, empresa=self.request.empresa).exists():
                initial["lead"] = lead_id
        if opportunity_id:
            from apps.crm.models import Opportunity

            if Opportunity.objects.filter(pk=opportunity_id, empresa=self.request.empresa).exists():
                initial["opportunity"] = opportunity_id
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
