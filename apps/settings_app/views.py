from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from apps.core.mixins import EmpresaMixin, HtmxResponseMixin
from apps.crm.models import PipelineStage
from apps.contracts.models import ContractTemplate
from apps.finance.forms import FinancialCategoryForm
from apps.finance.models import FinancialCategory
from apps.operations.forms import ServiceTypeForm
from apps.operations.models import ServiceType
from apps.proposals.models import ProposalTemplate

from .forms import ContractTemplateForm, PipelineStageForm, ProposalTemplateForm


# ---------------------------------------------------------------------------
# Settings Index
# ---------------------------------------------------------------------------


class SettingsIndexView(EmpresaMixin, TemplateView):
    template_name = "settings/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        empresa = self.request.empresa
        context["service_types_count"] = ServiceType.objects.filter(
            empresa=empresa
        ).count()
        context["pipeline_stages_count"] = PipelineStage.objects.filter(
            pipeline__empresa=empresa
        ).count()
        context["proposal_templates_count"] = ProposalTemplate.objects.filter(
            empresa=empresa
        ).count()
        context["contract_templates_count"] = ContractTemplate.objects.filter(
            empresa=empresa
        ).count()
        context["categories_count"] = FinancialCategory.objects.filter(
            empresa=empresa
        ).count()
        return context


# ---------------------------------------------------------------------------
# ServiceType Views
# ---------------------------------------------------------------------------


class ServiceTypeListView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = ServiceType
    template_name = "settings/service_type_list.html"
    partial_template_name = "settings/partials/_service_type_table.html"
    context_object_name = "service_types"
    paginate_by = 25


class ServiceTypeCreateView(EmpresaMixin, HtmxResponseMixin, CreateView):
    model = ServiceType
    form_class = ServiceTypeForm
    template_name = "settings/service_type_form.html"
    partial_template_name = "settings/partials/_service_type_form.html"
    success_url = reverse_lazy("settings_app:index")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Tipo de serviço criado com sucesso.")
        return response


class ServiceTypeUpdateView(EmpresaMixin, HtmxResponseMixin, UpdateView):
    model = ServiceType
    form_class = ServiceTypeForm
    template_name = "settings/service_type_form.html"
    partial_template_name = "settings/partials/_service_type_form.html"
    success_url = reverse_lazy("settings_app:index")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Tipo de serviço atualizado com sucesso.")
        return response


class ServiceTypeDeleteView(EmpresaMixin, DeleteView):
    model = ServiceType
    success_url = reverse_lazy("settings_app:service_type_list")
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        messages.success(request, "Tipo de serviço excluído com sucesso.")
        return self.delete(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# PipelineStage Views
# ---------------------------------------------------------------------------


class PipelineStagesView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = PipelineStage
    template_name = "settings/pipeline_stage_list.html"
    partial_template_name = "settings/partials/_pipeline_stage_table.html"
    context_object_name = "pipeline_stages"
    paginate_by = 25

    def get_queryset(self):
        return PipelineStage.objects.filter(
            pipeline__empresa=self.request.empresa
        ).select_related("pipeline").order_by("pipeline__name", "order")


class PipelineStageCreateView(EmpresaMixin, HtmxResponseMixin, CreateView):
    model = PipelineStage
    form_class = PipelineStageForm
    template_name = "settings/pipeline_stage_form.html"
    partial_template_name = "settings/partials/_pipeline_stage_form.html"
    success_url = reverse_lazy("settings_app:pipeline_stages")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Etapa do pipeline criada com sucesso.")
        return response


class PipelineStageUpdateView(EmpresaMixin, HtmxResponseMixin, UpdateView):
    model = PipelineStage
    form_class = PipelineStageForm
    template_name = "settings/pipeline_stage_form.html"
    partial_template_name = "settings/partials/_pipeline_stage_form.html"
    success_url = reverse_lazy("settings_app:pipeline_stages")

    def get_queryset(self):
        return PipelineStage.objects.filter(
            pipeline__empresa=self.request.empresa
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Etapa do pipeline atualizada com sucesso.")
        return response


class PipelineStageDeleteView(EmpresaMixin, DeleteView):
    model = PipelineStage
    success_url = reverse_lazy("settings_app:pipeline_stages")
    http_method_names = ["post"]

    def get_queryset(self):
        return PipelineStage.objects.filter(
            pipeline__empresa=self.request.empresa
        )

    def post(self, request, *args, **kwargs):
        try:
            response = self.delete(request, *args, **kwargs)
            messages.success(request, "Etapa do pipeline excluída com sucesso.")
            return response
        except Exception:
            messages.error(
                request,
                "Não foi possível excluir esta etapa. Existem oportunidades vinculadas.",
            )
            return self.get(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# ProposalTemplate Views
# ---------------------------------------------------------------------------


class ProposalTemplatesView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = ProposalTemplate
    template_name = "settings/proposal_template_list.html"
    partial_template_name = "settings/partials/_proposal_template_table.html"
    context_object_name = "proposal_templates"
    paginate_by = 25


class ProposalTemplateCreateView(EmpresaMixin, HtmxResponseMixin, CreateView):
    model = ProposalTemplate
    form_class = ProposalTemplateForm
    template_name = "settings/proposal_template_form.html"
    partial_template_name = "settings/partials/_proposal_template_form.html"
    success_url = reverse_lazy("settings_app:proposal_templates")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Template de proposta criado com sucesso.")
        return response


class ProposalTemplateUpdateView(EmpresaMixin, HtmxResponseMixin, UpdateView):
    model = ProposalTemplate
    form_class = ProposalTemplateForm
    template_name = "settings/proposal_template_form.html"
    partial_template_name = "settings/partials/_proposal_template_form.html"
    success_url = reverse_lazy("settings_app:proposal_templates")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Template de proposta atualizado com sucesso.")
        return response


class ProposalTemplateDeleteView(EmpresaMixin, DeleteView):
    model = ProposalTemplate
    success_url = reverse_lazy("settings_app:proposal_templates")
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        messages.success(request, "Template de proposta excluído com sucesso.")
        return self.delete(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# ContractTemplate Views
# ---------------------------------------------------------------------------


class ContractTemplatesView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = ContractTemplate
    template_name = "settings/contract_template_list.html"
    partial_template_name = "settings/partials/_contract_template_table.html"
    context_object_name = "contract_templates"
    paginate_by = 25


class ContractTemplateCreateView(EmpresaMixin, HtmxResponseMixin, CreateView):
    model = ContractTemplate
    form_class = ContractTemplateForm
    template_name = "settings/contract_template_form.html"
    partial_template_name = "settings/partials/_contract_template_form.html"
    success_url = reverse_lazy("settings_app:contract_templates")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Template de contrato criado com sucesso.")
        return response


class ContractTemplateUpdateView(EmpresaMixin, HtmxResponseMixin, UpdateView):
    model = ContractTemplate
    form_class = ContractTemplateForm
    template_name = "settings/contract_template_form.html"
    partial_template_name = "settings/partials/_contract_template_form.html"
    success_url = reverse_lazy("settings_app:contract_templates")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Template de contrato atualizado com sucesso.")
        return response


class ContractTemplateDeleteView(EmpresaMixin, DeleteView):
    model = ContractTemplate
    success_url = reverse_lazy("settings_app:contract_templates")
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        messages.success(request, "Template de contrato excluído com sucesso.")
        return self.delete(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# FinancialCategory Views
# ---------------------------------------------------------------------------


class FinancialCategoryListView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = FinancialCategory
    template_name = "settings/category_list.html"
    partial_template_name = "settings/partials/_category_table.html"
    context_object_name = "categories"
    paginate_by = 25


class FinancialCategoryCreateView(EmpresaMixin, HtmxResponseMixin, CreateView):
    model = FinancialCategory
    form_class = FinancialCategoryForm
    template_name = "settings/category_form.html"
    partial_template_name = "settings/partials/_category_form.html"
    success_url = reverse_lazy("settings_app:index")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Categoria financeira criada com sucesso.")
        return response


class FinancialCategoryUpdateView(EmpresaMixin, HtmxResponseMixin, UpdateView):
    model = FinancialCategory
    form_class = FinancialCategoryForm
    template_name = "settings/category_form.html"
    partial_template_name = "settings/partials/_category_form.html"
    success_url = reverse_lazy("settings_app:index")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Categoria financeira atualizada com sucesso.")
        return response


class FinancialCategoryDeleteView(EmpresaMixin, DeleteView):
    model = FinancialCategory
    success_url = reverse_lazy("settings_app:category_list")
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        messages.success(request, "Categoria financeira excluída com sucesso.")
        return self.delete(request, *args, **kwargs)
