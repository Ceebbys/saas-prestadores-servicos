from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from apps.accounts.models import Membership
from apps.core.mixins import EmpresaMixin, HtmxResponseMixin
from apps.crm.models import PipelineStage
from apps.contracts.models import ContractTemplate
from apps.finance.forms import BankAccountForm, FinancialCategoryForm
from apps.finance.models import BankAccount, FinancialCategory
from apps.operations.forms import ServiceTypeForm, TeamForm
from apps.operations.models import ServiceType, Team, TeamMember
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
        context["bank_accounts_count"] = BankAccount.objects.filter(
            empresa=empresa
        ).count()
        context["teams_count"] = Team.objects.filter(
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

    def get_context_data(self, **kwargs):
        from apps.proposals.forms import ProposalTemplateItemForm

        context = super().get_context_data(**kwargs)
        context["item_form"] = ProposalTemplateItemForm()
        context["template_items"] = self.object.default_items.all()
        context["template"] = self.object  # alias usado pelo partial
        return context

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


# ---------------------------------------------------------------------------
# Bank Accounts
# ---------------------------------------------------------------------------


class BankAccountListView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = BankAccount
    template_name = "settings/bank_account_list.html"
    partial_template_name = "settings/partials/_bank_account_table.html"
    context_object_name = "accounts"
    paginate_by = 25


class BankAccountCreateView(EmpresaMixin, HtmxResponseMixin, CreateView):
    model = BankAccount
    form_class = BankAccountForm
    template_name = "settings/bank_account_form.html"
    partial_template_name = "settings/partials/_bank_account_form.html"
    success_url = reverse_lazy("settings_app:bank_account_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Conta bancária criada com sucesso.")
        return response


class BankAccountUpdateView(EmpresaMixin, HtmxResponseMixin, UpdateView):
    model = BankAccount
    form_class = BankAccountForm
    template_name = "settings/bank_account_form.html"
    partial_template_name = "settings/partials/_bank_account_form.html"
    success_url = reverse_lazy("settings_app:bank_account_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Conta bancária atualizada com sucesso.")
        return response


class BankAccountDeleteView(EmpresaMixin, DeleteView):
    model = BankAccount
    success_url = reverse_lazy("settings_app:bank_account_list")
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        messages.success(request, "Conta bancária excluída com sucesso.")
        return self.delete(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


class TeamListView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = Team
    template_name = "settings/team_list.html"
    partial_template_name = "settings/partials/_team_table.html"
    context_object_name = "teams"
    paginate_by = 25

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("leader")
            .prefetch_related("team_members__user")
        )


class TeamCreateView(EmpresaMixin, HtmxResponseMixin, CreateView):
    model = Team
    form_class = TeamForm
    template_name = "settings/team_form.html"
    partial_template_name = "settings/partials/_team_form.html"
    success_url = reverse_lazy("settings_app:team_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Equipe criada com sucesso.")
        return response


class TeamUpdateView(EmpresaMixin, HtmxResponseMixin, UpdateView):
    model = Team
    form_class = TeamForm
    template_name = "settings/team_form.html"
    partial_template_name = "settings/partials/_team_form.html"
    success_url = reverse_lazy("settings_app:team_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["team_members"] = self.object.team_members.select_related(
            "user"
        ).all()
        empresa = self.request.empresa
        member_user_ids = self.object.team_members.values_list(
            "user_id", flat=True
        )
        available_user_ids = Membership.objects.filter(
            empresa=empresa, is_active=True
        ).values_list("user_id", flat=True)
        from apps.accounts.models import User

        context["available_users"] = User.objects.filter(
            id__in=available_user_ids
        ).exclude(id__in=member_user_ids)
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Equipe atualizada com sucesso.")
        return response


class TeamDeleteView(EmpresaMixin, DeleteView):
    model = Team
    success_url = reverse_lazy("settings_app:team_list")
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        messages.success(request, "Equipe excluída com sucesso.")
        return self.delete(request, *args, **kwargs)


class TeamMemberAddView(EmpresaMixin, View):
    """Adiciona um membro à equipe via HTMX."""

    def post(self, request, pk):
        team = get_object_or_404(Team, pk=pk, empresa=request.empresa)
        user_id = request.POST.get("user_id")
        if user_id:
            # Valida que user pertence à empresa
            if Membership.objects.filter(
                empresa=request.empresa, user_id=user_id, is_active=True
            ).exists():
                TeamMember.objects.get_or_create(
                    team=team,
                    user_id=user_id,
                    defaults={"role": TeamMember.Role.MEMBER},
                )
        if request.htmx:
            return redirect("settings_app:team_update", pk=team.pk)
        messages.success(request, "Membro adicionado com sucesso.")
        return redirect("settings_app:team_update", pk=team.pk)


class TeamMemberRemoveView(EmpresaMixin, View):
    """Remove um membro da equipe via HTMX."""

    def post(self, request, pk, member_pk):
        team = get_object_or_404(Team, pk=pk, empresa=request.empresa)
        TeamMember.objects.filter(pk=member_pk, team=team).delete()
        if request.htmx:
            return redirect("settings_app:team_update", pk=team.pk)
        messages.success(request, "Membro removido com sucesso.")
        return redirect("settings_app:team_update", pk=team.pk)


class TeamMemberRoleView(EmpresaMixin, View):
    """Altera o papel de um membro da equipe."""

    def post(self, request, pk, member_pk):
        team = get_object_or_404(Team, pk=pk, empresa=request.empresa)
        member = get_object_or_404(TeamMember, pk=member_pk, team=team)
        new_role = request.POST.get("role", TeamMember.Role.MEMBER)
        if new_role in dict(TeamMember.Role.choices):
            member.role = new_role
            member.save(update_fields=["role", "updated_at"])
        if request.htmx:
            return redirect("settings_app:team_update", pk=team.pk)
        messages.success(request, "Papel atualizado com sucesso.")
        return redirect("settings_app:team_update", pk=team.pk)
