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

from .forms import LeadContactForm, LeadForm, OpportunityForm
from .models import Lead, LeadContact, Opportunity, Pipeline, PipelineStage


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
        qs = (
            super()
            .get_queryset()
            .select_related("pipeline_stage", "assigned_to", "contato")
        )
        q = self.request.GET.get("q", "").strip()
        stage_id = self.request.GET.get("pipeline_stage", "").strip()
        source = self.request.GET.get("source", "").strip()

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(contato__name__icontains=q)
                | Q(contato__cpf_cnpj_normalized__icontains=q)
                | Q(contato__email__icontains=q)
                | Q(contato__phone__icontains=q)
                | Q(contato__whatsapp__icontains=q)
                | Q(email__icontains=q)
                | Q(company__icontains=q)
                | Q(cpf__icontains=q)
                | Q(cnpj__icontains=q)
            )
        if stage_id:
            qs = qs.filter(pipeline_stage_id=stage_id)
        if source:
            qs = qs.filter(source=source)

        return qs.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["stage_choices"] = _get_stage_choices(self.request.empresa)
        context["source_choices"] = Lead.Source.choices
        context["current_stage"] = self.request.GET.get("pipeline_stage", "")
        context["current_source"] = self.request.GET.get("source", "")
        context["current_q"] = self.request.GET.get("q", "")
        return context


class LeadDetailView(EmpresaMixin, DetailView):
    model = Lead
    template_name = "crm/lead_detail.html"
    context_object_name = "lead"

    def get_queryset(self):
        return super().get_queryset().select_related("pipeline_stage", "assigned_to")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["stage_choices"] = _get_stage_choices(self.request.empresa)
        context["contacts"] = self.object.contacts.select_related("user")[:50]
        context["contact_form"] = LeadContactForm()
        return context


def _get_stage_choices(empresa):
    pipeline = Pipeline.objects.filter(empresa=empresa, is_default=True).first()
    if pipeline is None:
        pipeline = Pipeline.objects.filter(empresa=empresa).first()
    if pipeline is None:
        return PipelineStage.objects.none()
    return pipeline.stages.order_by("order")


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

    def get_initial(self):
        """If URL has ?contato=ID, pre-select that contato in 'search' mode."""
        initial = super().get_initial()
        contato_id = self.request.GET.get("contato")
        if contato_id:
            from apps.contacts.models import Contato
            contato = Contato.objects.filter(
                pk=contato_id, empresa=self.request.empresa
            ).first()
            if contato:
                initial["contato"] = contato.pk
                initial["contact_mode"] = "search"
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Resolve preselected contato (if any) for the card preview.
        from apps.contacts.models import Contato
        contato_id = (
            self.request.POST.get("contato")
            or self.request.GET.get("contato")
        )
        if contato_id:
            context["preselected_contato"] = Contato.objects.filter(
                pk=contato_id, empresa=self.request.empresa
            ).first()
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Lead criado com sucesso.")
        if self.request.htmx:
            qs = Lead.objects.filter(empresa=self.request.empresa).select_related(
                "contato", "pipeline_stage"
            )
            return self.render_to_response(
                self.get_context_data(leads=qs, object_list=qs),
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
                .prefetch_related(
                    "opportunities",
                    "opportunities__lead",
                    "opportunities__lead__contato",
                )
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


class LeadMoveView(EmpresaMixin, View):
    """Move um lead para outra etapa da pipeline."""

    def post(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk, empresa=request.empresa)
        stage_id = request.POST.get("stage_id") or request.POST.get("pipeline_stage")

        stage = PipelineStage.objects.filter(
            pk=stage_id, pipeline__empresa=request.empresa
        ).first()
        if not stage:
            messages.error(request, "Etapa inválida.")
            return redirect("crm:lead_detail", pk=lead.pk)

        lead.pipeline_stage = stage
        lead.save(update_fields=["pipeline_stage", "updated_at"])
        messages.success(request, "Etapa do lead atualizada.")
        return redirect("crm:lead_detail", pk=lead.pk)


class LeadContactCardView(EmpresaMixin, View):
    """Retorna um card HTML com resumo do Contato selecionado (HTMX)."""

    def get(self, request, contato_id):
        from apps.contacts.models import Contato
        from django.template.loader import render_to_string
        from django.http import HttpResponse

        contato = get_object_or_404(
            Contato, pk=contato_id, empresa=request.empresa
        )
        html = render_to_string(
            "crm/partials/_contact_card.html",
            {"contato": contato},
            request=request,
        )
        return HttpResponse(html)


class LeadContactCreateView(EmpresaMixin, View):
    """Registra um novo contato/follow-up com um lead."""

    def post(self, request, lead_id):
        lead = get_object_or_404(Lead, pk=lead_id, empresa=request.empresa)
        form = LeadContactForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Preencha os campos corretamente.")
            return redirect("crm:lead_detail", pk=lead.pk)

        contact = form.save(commit=False)
        contact.empresa = request.empresa
        contact.lead = lead
        contact.user = request.user if request.user.is_authenticated else None
        contact.save()
        messages.success(request, "Contato registrado com sucesso.")
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
