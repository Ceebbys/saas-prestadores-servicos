from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from apps.core.mixins import EmpresaMixin, HtmxResponseMixin

from .forms import LeadForm, OpportunityForm
from .models import Lead, Opportunity, Pipeline, PipelineStage


# ---------------------------------------------------------------------------
# Lead Views
# ---------------------------------------------------------------------------


class LeadListView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = Lead
    template_name = "crm/lead_list.html"
    partial_template_name = "crm/partials/_lead_table.html"
    context_object_name = "leads"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        source = self.request.GET.get("source", "").strip()

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(email__icontains=q)
                | Q(company__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
        if source:
            qs = qs.filter(source=source)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = Lead.Status.choices
        context["source_choices"] = Lead.Source.choices
        context["current_status"] = self.request.GET.get("status", "")
        context["current_source"] = self.request.GET.get("source", "")
        context["current_q"] = self.request.GET.get("q", "")
        return context


class LeadDetailView(EmpresaMixin, DetailView):
    model = Lead
    template_name = "crm/lead_detail.html"
    context_object_name = "lead"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = Lead.Status.choices
        return context


class LeadCreateView(EmpresaMixin, HtmxResponseMixin, CreateView):
    model = Lead
    form_class = LeadForm
    template_name = "crm/lead_form.html"
    partial_template_name = "crm/partials/_lead_form.html"
    success_url = reverse_lazy("crm:lead_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Lead criado com sucesso.")
        if self.request.htmx:
            qs = Lead.objects.filter(empresa=self.request.empresa)
            return self.render_to_response(
                self.get_context_data(leads=qs),
                template_name="crm/partials/_lead_table.html",
            )
        return response

    def render_to_response(self, context, **kwargs):
        template_name = kwargs.pop("template_name", None)
        if template_name:
            from django.template.loader import render_to_string
            from django.http import HttpResponse

            html = render_to_string(template_name, context, request=self.request)
            return HttpResponse(html)
        return super().render_to_response(context, **kwargs)


class LeadUpdateView(EmpresaMixin, HtmxResponseMixin, UpdateView):
    model = Lead
    form_class = LeadForm
    template_name = "crm/lead_form.html"
    partial_template_name = "crm/partials/_lead_form.html"
    success_url = reverse_lazy("crm:lead_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Lead atualizado com sucesso.")
        if self.request.htmx:
            qs = Lead.objects.filter(empresa=self.request.empresa)
            return self.render_to_response(
                self.get_context_data(leads=qs),
                template_name="crm/partials/_lead_table.html",
            )
        return response

    def render_to_response(self, context, **kwargs):
        template_name = kwargs.pop("template_name", None)
        if template_name:
            from django.template.loader import render_to_string
            from django.http import HttpResponse

            html = render_to_string(template_name, context, request=self.request)
            return HttpResponse(html)
        return super().render_to_response(context, **kwargs)


class LeadDeleteView(EmpresaMixin, DeleteView):
    model = Lead
    success_url = reverse_lazy("crm:lead_list")
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        messages.success(request, "Lead excluído com sucesso.")
        return self.delete(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Pipeline / Opportunity Views
# ---------------------------------------------------------------------------


class PipelineBoardView(EmpresaMixin, HtmxResponseMixin, TemplateView):
    template_name = "crm/pipeline_board.html"
    partial_template_name = "crm/partials/_pipeline_board.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pipeline = Pipeline.objects.filter(
            empresa=self.request.empresa, is_default=True
        ).first()

        stages = []
        if pipeline:
            stages = (
                pipeline.stages.annotate(
                    opportunity_count=Count("opportunities"),
                    total_value=Sum("opportunities__value"),
                )
                .prefetch_related("opportunities", "opportunities__lead")
                .order_by("order")
            )

        context["pipeline"] = pipeline
        context["stages"] = stages
        return context


class OpportunityCreateView(EmpresaMixin, HtmxResponseMixin, CreateView):
    model = Opportunity
    form_class = OpportunityForm
    template_name = "crm/opportunity_form.html"
    partial_template_name = "crm/partials/_opportunity_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def get_success_url(self):
        return reverse_lazy("crm:pipeline_board")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Oportunidade criada com sucesso.")
        if self.request.htmx:
            view = PipelineBoardView()
            view.request = self.request
            view.kwargs = {}
            context = view.get_context_data()
            from django.template.loader import render_to_string
            from django.http import HttpResponse

            html = render_to_string(
                "crm/partials/_pipeline_board.html", context, request=self.request
            )
            return HttpResponse(html)
        return response


class OpportunityUpdateView(EmpresaMixin, HtmxResponseMixin, UpdateView):
    model = Opportunity
    form_class = OpportunityForm
    template_name = "crm/opportunity_form.html"
    partial_template_name = "crm/partials/_opportunity_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def get_success_url(self):
        return reverse_lazy("crm:opportunity_detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Oportunidade atualizada com sucesso.")
        return response


class OpportunityDeleteView(EmpresaMixin, DeleteView):
    model = Opportunity
    success_url = reverse_lazy("crm:pipeline_board")
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        messages.success(request, "Oportunidade excluída com sucesso.")
        return self.delete(request, *args, **kwargs)


class OpportunityDetailView(EmpresaMixin, DetailView):
    model = Opportunity
    template_name = "crm/opportunity_detail.html"
    context_object_name = "opportunity"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object.pipeline:
            context["stages"] = self.object.pipeline.stages.order_by("order")
        # Related proposals for this lead
        from apps.proposals.models import Proposal

        context["related_proposals"] = Proposal.objects.filter(
            empresa=self.request.empresa,
            lead=self.object.lead,
        ).order_by("-created_at")[:5]
        return context


class LeadStatusView(EmpresaMixin, View):
    """Altera o status de um lead."""

    def post(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk, empresa=request.empresa)
        new_status = request.POST.get("status")

        if new_status in dict(Lead.Status.choices):
            lead.status = new_status
            lead.save(update_fields=["status", "updated_at"])
            messages.success(request, "Status do lead atualizado.")
        else:
            messages.error(request, "Status inválido.")

        return redirect("crm:lead_detail", pk=lead.pk)


class OpportunityMoveView(EmpresaMixin, View):
    """Move uma oportunidade para outra etapa do pipeline via POST."""

    def post(self, request, pk):
        opportunity = get_object_or_404(
            Opportunity, pk=pk, empresa=request.empresa
        )
        stage_id = request.POST.get("stage_id")
        stage = get_object_or_404(
            PipelineStage, pk=stage_id, pipeline=opportunity.pipeline
        )

        opportunity.current_stage = stage

        if stage.is_won:
            opportunity.won_at = timezone.now()
            opportunity.lost_at = None
            opportunity.lost_reason = ""
        elif stage.is_lost:
            opportunity.lost_at = timezone.now()
            opportunity.won_at = None
            opportunity.lost_reason = request.POST.get("lost_reason", "")
        else:
            opportunity.won_at = None
            opportunity.lost_at = None
            opportunity.lost_reason = ""

        opportunity.save()

        if request.htmx:
            view = PipelineBoardView()
            view.request = request
            view.kwargs = {}
            context = view.get_context_data()
            from django.template.loader import render_to_string
            from django.http import HttpResponse

            html = render_to_string(
                "crm/partials/_pipeline_board.html", context, request=request
            )
            return HttpResponse(html)

        return redirect("crm:pipeline_board")
