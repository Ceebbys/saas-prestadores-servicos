import logging

from django.conf import settings as django_settings
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# WhatsApp Config
# ---------------------------------------------------------------------------


class WhatsAppConfigView(EmpresaMixin, TemplateView):
    """Página de configuração do WhatsApp por empresa."""

    template_name = "settings/whatsapp_config.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        empresa = self.request.empresa
        try:
            context["whatsapp_config"] = empresa.whatsapp_config
        except Exception:
            context["whatsapp_config"] = None

        from apps.chatbot.models import ChatbotFlow

        context["active_flow"] = ChatbotFlow.objects.filter(
            empresa=empresa, channel="whatsapp", is_active=True,
        ).first()
        context["has_global_api"] = bool(getattr(django_settings, "EVOLUTION_API_URL", ""))

        # URL absoluta do webhook auto (multi-tenant)
        webhook_path = "/chatbot/evolution/"
        context["webhook_auto_url"] = request.build_absolute_uri(webhook_path) if (
            request := self.request
        ) else webhook_path

        return context


class WhatsAppConfigSaveView(EmpresaMixin, View):
    """Salva configuração do WhatsApp e tenta criar/atualizar instância."""

    # A Evolution API rejeita nomes com espaços, caracteres especiais, etc.
    _INSTANCE_NAME_RE = __import__("re").compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{1,98}$")

    # Palavras-chave nas respostas de erro da Evolution que indicam que o
    # nome da instância já está em uso (v2.2.x retorna 403, v2.1 retornava
    # 409 — ambos carregam alguma dessas frases na mensagem de erro).
    _ALREADY_EXISTS_KEYWORDS = (
        "already in use",
        "already exists",
        "is already in use",
        "em uso",
    )

    @classmethod
    def _is_already_exists_error(cls, status_code: int, detail) -> bool:
        """Detecta 'instância já existe' olhando status e corpo da resposta."""
        if status_code == 409:
            return True
        if status_code == 403:
            # A Evolution v2.2+ retorna 403 genérico para vários erros; só
            # consideramos "já existe" se a mensagem bater com as keywords.
            try:
                body_text = str(detail).lower()
            except Exception:
                return False
            return any(kw in body_text for kw in cls._ALREADY_EXISTS_KEYWORDS)
        return False

    @staticmethod
    def _fetch_instance_token(api_url: str, api_key: str, instance_name: str) -> str:
        """Busca o apikey da instância existente na Evolution.

        Lida com ambos os formatos de resposta:
          - v2.2.x: `[{"instance": {"instanceName": "...", "apikey": "..."}, "hash": {...}}]`
          - v2.3.x: `[{"name": "...", "id": "...", "token": "..."}]` (campos planos)

        Retorna string vazia se não encontrar.
        """
        try:
            import httpx

            resp = httpx.get(
                f"{api_url.rstrip('/')}/instance/fetchInstances",
                headers={"apikey": api_key},
                params={"instanceName": instance_name},
                timeout=10.0,
            )
            if resp.status_code != 200:
                return ""
            data = resp.json()
            instances = data if isinstance(data, list) else [data]
            for inst in instances:
                if not isinstance(inst, dict):
                    continue
                # Formato v2.2.x (aninhado em "instance")
                nested = inst.get("instance") or {}
                nested_name = nested.get("instanceName") or nested.get("name") or ""
                flat_name = inst.get("name") or inst.get("instanceName") or ""
                if nested_name != instance_name and flat_name != instance_name:
                    continue
                # Tenta múltiplos locais para o token (apikey / token / hash)
                hash_val = inst.get("hash")
                hash_token = ""
                if isinstance(hash_val, dict):
                    hash_token = hash_val.get("apikey", "")
                elif isinstance(hash_val, str):
                    hash_token = hash_val
                return (
                    nested.get("apikey")
                    or inst.get("apikey")
                    or inst.get("token")
                    or hash_token
                    or ""
                )
        except Exception:
            logger.exception("Failed to fetch instance details for '%s'", instance_name)
        return ""

    def post(self, request):
        empresa = request.empresa
        instance_name = request.POST.get("instance_name", "").strip()
        phone_number = request.POST.get("phone_number", "").strip()
        api_url = request.POST.get("api_url", "").strip()
        api_key = request.POST.get("api_key", "").strip()

        if not instance_name:
            messages.error(request, "O nome da instância é obrigatório.")
            return redirect("settings_app:whatsapp_config")

        # Validar formato: apenas letras, números, hifens e underscores (sem espaços)
        if not self._INSTANCE_NAME_RE.match(instance_name):
            messages.error(
                request,
                "Nome de instância inválido. Use apenas letras, números, hifens e underscores "
                "(ex: minha-empresa-wa). Espaços e caracteres especiais não são permitidos.",
            )
            return redirect("settings_app:whatsapp_config")

        from apps.chatbot.models import WhatsAppConfig

        # Verificar conflito de nome com outra empresa
        conflict = WhatsAppConfig.objects.filter(
            instance_name=instance_name,
        ).exclude(empresa=empresa).exists()
        if conflict:
            messages.error(
                request,
                f"O nome de instância '{instance_name}' já está em uso por outra empresa.",
            )
            return redirect("settings_app:whatsapp_config")

        config, created = WhatsAppConfig.objects.get_or_create(
            empresa=empresa,
            defaults={
                "instance_name": instance_name,
                "phone_number": phone_number,
                "api_url": api_url,
                "api_key": api_key,
            },
        )
        if not created:
            old_instance_name = config.instance_name  # capturar antes de sobrescrever
            config.instance_name = instance_name
            config.phone_number = phone_number
            config.api_url = api_url
            config.api_key = api_key
            config.save(update_fields=["instance_name", "phone_number", "api_url", "api_key", "updated_at"])
            # Limpar token antigo ao renomear instância (será gerado novo na criação)
            if old_instance_name != instance_name:
                config.instance_token = ""
                config.save(update_fields=["instance_token", "updated_at"])

        # Tentar criar instância na Evolution API
        effective_url = api_url or getattr(django_settings, "EVOLUTION_API_URL", "")
        effective_key = api_key or getattr(django_settings, "EVOLUTION_API_KEY", "")

        if effective_url and effective_key:
            try:
                import httpx

                # Evolution API v2: payload correto para criação de instância
                payload = {
                    "instanceName": instance_name,
                    "qrcode": True,
                    "integration": "WHATSAPP-BAILEYS",
                }
                resp = httpx.post(
                    f"{effective_url.rstrip('/')}/instance/create",
                    headers={"Content-Type": "application/json", "apikey": effective_key},
                    json=payload,
                    timeout=15.0,
                )
                if resp.status_code in (200, 201):
                    # Capturar e salvar o token específico desta instância
                    # Evolution API v2.2.x retorna `hash` como string direta; versões anteriores
                    # retornavam um objeto {apikey: "..."}. Tentamos ambos os formatos.
                    try:
                        resp_data = resp.json()
                        hash_val = resp_data.get("hash")
                        if isinstance(hash_val, dict):
                            hash_token = hash_val.get("apikey", "")
                        elif isinstance(hash_val, str):
                            hash_token = hash_val
                        else:
                            hash_token = ""
                        instance_token = (
                            hash_token
                            or resp_data.get("instance", {}).get("apikey")
                            or resp_data.get("apikey")
                            or ""
                        )
                        if instance_token:
                            config.instance_token = instance_token
                            config.save(update_fields=["instance_token", "updated_at"])
                    except Exception:
                        logger.exception("Failed to parse instance token from create response")
                    messages.success(
                        request,
                        f"Instância '{instance_name}' criada com sucesso. "
                        "Agora escaneie o QR Code abaixo com seu celular.",
                    )
                else:
                    # Lê corpo do erro UMA vez para decidir e logar.
                    try:
                        err_detail = resp.json()
                    except Exception:
                        err_detail = resp.text[:300]

                    if self._is_already_exists_error(resp.status_code, err_detail):
                        # Instância já existe (409 legado ou 403 v2.2+).
                        # Busca token só se ainda não temos um salvo.
                        if not config.instance_token:
                            token = self._fetch_instance_token(
                                effective_url, effective_key, instance_name,
                            )
                            if token:
                                config.instance_token = token
                                config.save(
                                    update_fields=["instance_token", "updated_at"],
                                )
                                logger.info(
                                    "Captured token from existing instance '%s'",
                                    instance_name,
                                )
                        messages.success(
                            request,
                            f"Instância '{instance_name}' já existe na Evolution API. "
                            "Configuração salva.",
                        )
                    else:
                        logger.warning(
                            "Evolution API create instance failed %s: %s",
                            resp.status_code, err_detail,
                        )
                        messages.warning(
                            request,
                            f"Configuração salva, mas a Evolution API retornou erro "
                            f"{resp.status_code}: {err_detail}. Verifique a URL, a "
                            "API Key e o nome da instância.",
                        )
            except Exception:
                logger.exception("Error creating Evolution API instance")
                messages.warning(
                    request,
                    "Configuração salva. Não foi possível contatar a Evolution API — "
                    "verifique se a URL está correta e o serviço está no ar.",
                )
        else:
            messages.success(
                request,
                "Configuração salva. Para ativar o WhatsApp, configure as variáveis "
                "EVOLUTION_API_URL e EVOLUTION_API_KEY no servidor.",
            )

        return redirect("settings_app:whatsapp_config")


class WhatsAppStatusView(EmpresaMixin, View):
    """Verifica o status de conexão da instância WhatsApp."""

    def get(self, request):
        empresa = request.empresa
        try:
            config = empresa.whatsapp_config
        except Exception:
            return JsonResponse({"error": "Nenhuma configuração WhatsApp encontrada."}, status=404)

        effective_url = config.effective_api_url
        # Para operações de instância, usar o token específico (mais restrito e seguro)
        effective_key = config.effective_instance_key

        if not effective_url or not effective_key:
            return JsonResponse({"status": "not_configured", "is_connected": False})

        try:
            import httpx
            from django.utils import timezone

            resp = httpx.get(
                f"{effective_url.rstrip('/')}/instance/connectionState/{config.instance_name}",
                headers={"apikey": effective_key},
                timeout=8.0,
            )
            data = resp.json() if resp.status_code == 200 else {}
            state = data.get("instance", {}).get("state", "close")
            is_connected = state == "open"

            config.is_connected = is_connected
            if is_connected and not config.connected_at:
                config.connected_at = timezone.now()
                config.save(update_fields=["is_connected", "connected_at", "updated_at"])
            else:
                config.save(update_fields=["is_connected", "updated_at"])

            # Retornar JSON se requisição JSON, HTML (para HTMX badge swap) caso contrário
            if request.headers.get("Accept", "").startswith("application/json"):
                return JsonResponse({"status": state, "is_connected": is_connected})
            return self._badge_html(is_connected)
        except Exception:
            logger.exception("Error checking WhatsApp connection state")
            if request.headers.get("Accept", "").startswith("application/json"):
                return JsonResponse({"status": "error", "is_connected": False})
            return self._badge_html(False)

    def _badge_html(self, is_connected):
        from django.http import HttpResponse

        if is_connected:
            html = (
                '<span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs '
                'font-medium bg-green-100 text-green-700 ring-1 ring-green-200">'
                '<span class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>Conectado</span>'
            )
        else:
            html = (
                '<span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs '
                'font-medium bg-slate-100 text-slate-600 ring-1 ring-slate-200">'
                '<span class="w-2 h-2 rounded-full bg-slate-400"></span>Desconectado</span>'
            )
        return HttpResponse(html)


class WhatsAppQRCodeView(EmpresaMixin, View):
    """Busca e serve o QR code da instância diretamente da Evolution API v2.

    Compatível com Evolution API v2.1.x que retorna:
    - ``code``: texto raw para gerar QR code localmente
    - ``pairingCode``: código de 8 dígitos para parear manualmente
    - ``base64``: imagem QR pronta (versões mais antigas)
    - ``count``: 0 quando a conexão WebSocket ainda não foi estabelecida

    Retorna HTML parcial (para HTMX) com QR code ou pairing code.
    """

    def get(self, request):
        empresa = request.empresa
        try:
            config = empresa.whatsapp_config
        except Exception:
            return self._html_error("Nenhuma configuração WhatsApp encontrada.")

        effective_url = config.effective_api_url.rstrip("/")
        effective_key = config.effective_instance_key
        admin_key = config.effective_api_key

        if not effective_url or not effective_key:
            return self._html_error(
                "Servidor Evolution API não configurado. "
                "Adicione EVOLUTION_API_URL e EVOLUTION_API_KEY nas variáveis de ambiente."
            )

        try:
            import httpx
            from django.utils import timezone

            headers = {"apikey": effective_key}
            admin_headers = {"apikey": admin_key}
            inst = config.instance_name

            # 1. Verificar estado atual
            state_resp = httpx.get(
                f"{effective_url}/instance/connectionState/{inst}",
                headers=headers,
                timeout=8.0,
            )
            logger.info(
                "Evolution connectionState '%s': status=%s body=%s",
                inst, state_resp.status_code, state_resp.text[:300],
            )
            state_data = state_resp.json() if state_resp.status_code == 200 else {}
            state = state_data.get("instance", {}).get("state", "close")

            if state == "open":
                if not config.is_connected:
                    config.is_connected = True
                    config.connected_at = config.connected_at or timezone.now()
                    config.save(update_fields=["is_connected", "connected_at", "updated_at"])
                return self._html_connected(config)

            # 2. Tentar /instance/connect/ (endpoint primário v2)
            qr_result = self._try_connect_endpoint(effective_url, inst, headers)

            # 3. Fallback: tentar GET /instance/qrcode/{inst} (algumas versoes expoem este endpoint)
            if not qr_result:
                qr_result = self._try_qrcode_endpoint(effective_url, inst, headers)

            # 4. Se connect retornou count=0, tentar logout + reconnect
            if not qr_result:
                logger.info(
                    "Connect returned no QR (count=0), attempting logout+reconnect for '%s'",
                    inst,
                )
                qr_result = self._try_logout_reconnect(
                    effective_url, inst, admin_headers, headers,
                )

            if qr_result:
                return self._render_qr_result(qr_result)

            # 5. Estado connecting = WebSocket do Baileys tentando conectar
            if state == "connecting":
                return self._html_connecting()

            # Incluir resposta bruta no log para diagnostico
            connect_body = ""
            try:
                dbg_resp = httpx.get(
                    f"{effective_url}/instance/connect/{inst}",
                    headers=headers,
                    timeout=8.0,
                )
                connect_body = dbg_resp.text[:200]
            except Exception:
                connect_body = "(sem resposta)"

            return self._html_error(
                "QR code nao disponivel. A Evolution API nao retornou dados "
                "de QR/pairing code para esta instancia. Resposta da API: "
                f"{connect_body} "
                "Tente salvar a configuracao novamente para recriar a instancia."
            )

        except Exception:
            logger.exception("Error fetching WhatsApp QR code")
            return self._html_error(
                "Erro ao contatar a Evolution API. Verifique a URL configurada."
            )

    # ------------------------------------------------------------------
    # Extrair dados do QR code da resposta da Evolution API v2
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_qr_data(data: dict) -> dict | None:
        """Extrai dados de QR code da resposta da Evolution API v2.1.x/v2.2.x.

        Retorna dict com chaves possíveis:
        - ``base64_img``: imagem base64 pronta (data:image/...)
        - ``code``: texto raw para gerar QR code localmente
        - ``pairing_code``: código de pareamento de 8 dígitos

        Retorna None se nenhum dado de QR code estiver disponível.
        """
        qrcode_sub = data.get("qrcode") if isinstance(data.get("qrcode"), dict) else {}

        # count=0 significa "ainda conectando, sem QR"
        if (
            data.get("count", -1) == 0
            and not data.get("code")
            and not data.get("base64")
            and not qrcode_sub.get("code")
            and not qrcode_sub.get("base64")
        ):
            return None

        result = {}

        # Imagem base64 pronta (formato antigo ou futuro, em top-level ou nested em "qrcode")
        base64_val = data.get("base64") or qrcode_sub.get("base64", "")
        if base64_val:
            if base64_val.startswith("data:image"):
                result["base64_img"] = base64_val
            else:
                # Alguns forks retornam apenas o base64 cru sem prefixo data URI
                result["base64_img"] = f"data:image/png;base64,{base64_val}"

        # Texto raw do QR code (formato v2.1.x) — tanto top-level quanto em "qrcode"
        code_val = data.get("code") or qrcode_sub.get("code", "")
        if code_val and len(code_val) > 10:
            result["code"] = code_val

        # Pairing code de 8 dígitos — top-level ou nested
        pairing_val = data.get("pairingCode") or qrcode_sub.get("pairingCode", "")
        if pairing_val:
            result["pairing_code"] = pairing_val

        return result if result else None

    # ------------------------------------------------------------------
    # Tentativas de obter QR code
    # ------------------------------------------------------------------

    def _try_connect_endpoint(self, base_url, inst, headers):
        """Chama GET /instance/connect/{inst} e retorna dict de QR data ou None."""
        import httpx

        try:
            resp = httpx.get(
                f"{base_url}/instance/connect/{inst}",
                headers=headers,
                timeout=15.0,
            )
            logger.info(
                "Evolution connect '%s': status=%s body=%s",
                inst, resp.status_code, resp.text[:500],
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("instance", {}).get("state") == "open":
                    return None
                return self._extract_qr_data(data)
        except Exception:
            logger.exception("Error on /instance/connect/ for '%s'", inst)
        return None

    def _try_qrcode_endpoint(self, base_url, inst, headers):
        """Chama GET /instance/qrcode/{inst} como fallback alternativo.

        Algumas versoes/forks da Evolution API expoem um endpoint dedicado para QR
        separado de ``/instance/connect/``. O parametro ``image=false`` retorna o
        campo ``base64`` quando suportado.
        """
        import httpx

        try:
            resp = httpx.get(
                f"{base_url}/instance/qrcode/{inst}",
                headers=headers,
                params={"image": "false"},
                timeout=10.0,
            )
            logger.info(
                "Evolution qrcode '%s': status=%s body=%s",
                inst, resp.status_code, resp.text[:400],
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    return None
                if data.get("instance", {}).get("state") == "open":
                    return None
                return self._extract_qr_data(data)
        except Exception:
            logger.exception("Error on /instance/qrcode/ for '%s'", inst)
        return None

    def _try_logout_reconnect(self, base_url, inst, admin_headers, instance_headers):
        """Faz logout da instância e tenta reconectar para gerar novo QR."""
        import httpx
        import time

        try:
            logout_resp = httpx.delete(
                f"{base_url}/instance/logout/{inst}",
                headers=admin_headers,
                timeout=10.0,
            )
            logger.info(
                "Evolution logout '%s': status=%s body=%s",
                inst, logout_resp.status_code, logout_resp.text[:200],
            )

            # Dar tempo para o Baileys reiniciar o WebSocket
            time.sleep(3)

            retry_resp = httpx.get(
                f"{base_url}/instance/connect/{inst}",
                headers=instance_headers,
                timeout=15.0,
            )
            logger.info(
                "Evolution retry connect '%s': status=%s body=%s",
                inst, retry_resp.status_code, retry_resp.text[:500],
            )
            if retry_resp.status_code == 200:
                return self._extract_qr_data(retry_resp.json())
        except Exception:
            logger.exception("Logout+reconnect failed for '%s'", inst)
        return None

    # ------------------------------------------------------------------
    # Gerar QR code a partir do texto raw (code)
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_qr_base64(code_text: str) -> str:
        """Gera imagem PNG do QR code a partir do texto raw retornado pela Evolution API.

        Usa a lib ``qrcode`` para criar a imagem e retorna como data URI base64.
        """
        import io
        import base64
        import qrcode

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=8,
            border=2,
        )
        qr.add_data(code_text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64}"

    # ------------------------------------------------------------------
    # Helpers HTML parcial (HTMX swap)
    # ------------------------------------------------------------------

    def _render_qr_result(self, qr_result: dict):
        """Renderiza o resultado do QR code conforme o tipo de dado disponível."""
        from django.http import HttpResponse

        parts = []

        # Instrução principal
        parts.append(
            '<p class="text-xs text-slate-500">'
            "Abra o WhatsApp no celular &rarr; <strong>Aparelhos conectados</strong> &rarr; "
            "<strong>Conectar aparelho</strong>"
            "</p>"
        )

        # QR code como imagem
        if qr_result.get("base64_img"):
            img_src = qr_result["base64_img"]
        elif qr_result.get("code"):
            img_src = self._generate_qr_base64(qr_result["code"])
        else:
            img_src = None

        if img_src:
            parts.append(
                f'<img src="{img_src}" alt="QR Code WhatsApp" '
                f'class="w-52 h-52 rounded-xl border border-slate-200 shadow-sm">'
            )

        # Pairing code (código manual alternativo)
        if qr_result.get("pairing_code"):
            code = qr_result["pairing_code"]
            # Formatar como XXXX-XXXX
            formatted = f"{code[:4]}-{code[4:]}" if len(code) == 8 else code
            parts.append(
                '<div class="mt-2 p-3 bg-indigo-50 rounded-lg border border-indigo-200">'
                '<p class="text-xs text-indigo-600 font-medium mb-1">'
                "Ou use o código de pareamento:</p>"
                f'<p class="text-2xl font-mono font-bold text-indigo-800 tracking-widest">'
                f"{formatted}</p>"
                '<p class="text-xs text-indigo-400 mt-1">'
                "No WhatsApp &rarr; Aparelhos conectados &rarr; "
                "Conectar com número de telefone</p>"
                "</div>"
            )

        # Botão atualizar
        refresh_url = self.request.build_absolute_uri("")
        parts.append(
            '<p class="text-xs text-slate-400">'
            "O QR code expira em ~60s. "
            f'<span class="text-indigo-500 cursor-pointer underline" '
            f'hx-get="{refresh_url}" hx-target="#qrcode-container" hx-swap="innerHTML">'
            "Clique para atualizar</span></p>"
        )

        html = '<div class="flex flex-col items-center gap-3">' + "".join(parts) + "</div>"
        return HttpResponse(html)

    def _html_connected(self, config):
        from django.http import HttpResponse

        number = f" — {config.phone_number}" if config.phone_number else ""
        html = f"""
        <div class="flex flex-col items-center gap-3 py-4">
            <div class="w-14 h-14 rounded-full bg-green-100 flex items-center justify-center">
                <svg class="w-8 h-8 text-green-600" fill="none" stroke="currentColor"
                     viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round"
                     stroke-width="2" d="M5 13l4 4L19 7"/></svg>
            </div>
            <p class="text-base font-semibold text-green-700">WhatsApp Conectado{number}</p>
            <p class="text-xs text-slate-500">Seu número já está ativo e recebendo mensagens.</p>
        </div>
        """
        return HttpResponse(html)

    def _html_connecting(self):
        """Estado intermediário: WebSocket do Baileys tentando conectar ao WhatsApp."""
        from django.http import HttpResponse

        refresh_url = self.request.build_absolute_uri("")
        html = f"""
        <div class="flex flex-col items-center gap-3 py-4 text-center"
             hx-get="{refresh_url}" hx-target="#qrcode-container"
             hx-swap="innerHTML" hx-trigger="every 5s">
            <div class="w-10 h-10 border-4 border-indigo-200 border-t-indigo-600 rounded-full
                        animate-spin"></div>
            <p class="text-sm font-medium text-slate-700">Conectando ao WhatsApp...</p>
            <p class="text-xs text-slate-500">
                O servidor está estabelecendo conexão com o WhatsApp.<br>
                O QR code aparecerá automaticamente quando estiver pronto.
            </p>
            <p class="text-xs text-slate-400">Atualizando a cada 5 segundos...</p>
        </div>
        """
        return HttpResponse(html)

    def _html_error(self, message):
        from django.http import HttpResponse

        html = f"""
        <div class="flex flex-col items-center gap-2 py-4 text-center">
            <svg class="w-8 h-8 text-red-400" fill="none" stroke="currentColor"
                 viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round"
                 stroke-width="2" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            <p class="text-sm text-red-600">{message}</p>
        </div>
        """
        return HttpResponse(html)


# ---------------------------------------------------------------------------
# Pipeline Automation Rules — gatilhos proposta → pipeline (Etapa 7)
# ---------------------------------------------------------------------------

from apps.automation.models import PipelineAutomationRule  # noqa: E402

from .forms import PipelineAutomationRuleForm  # noqa: E402


class AutomationRuleListView(EmpresaMixin, ListView):
    model = PipelineAutomationRule
    template_name = "settings/automation_rule_list.html"
    context_object_name = "rules"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("target_pipeline", "target_stage")
            .order_by("priority", "name")
        )


class AutomationRuleCreateView(EmpresaMixin, CreateView):
    model = PipelineAutomationRule
    form_class = PipelineAutomationRuleForm
    template_name = "settings/automation_rule_form.html"
    success_url = reverse_lazy("settings_app:automation_rule_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Regra de automação criada com sucesso.")
        return response


class AutomationRuleUpdateView(EmpresaMixin, UpdateView):
    model = PipelineAutomationRule
    form_class = PipelineAutomationRuleForm
    template_name = "settings/automation_rule_form.html"
    success_url = reverse_lazy("settings_app:automation_rule_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Regra atualizada.")
        return response


class AutomationRuleDeleteView(EmpresaMixin, DeleteView):
    model = PipelineAutomationRule
    success_url = reverse_lazy("settings_app:automation_rule_list")
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        messages.success(request, "Regra removida.")
        return self.delete(request, *args, **kwargs)
