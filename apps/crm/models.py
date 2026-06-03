from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import SoftDeletableModel, TenantOwnedModel, TimestampedModel
from apps.core.validators import validate_cnpj, validate_cpf


class Lead(SoftDeletableModel, TenantOwnedModel):
    """Potencial cliente captado pelo CRM.

    Soft-delete: `Lead.objects` esconde excluídos; `Lead.all_objects` retorna tudo.
    `Lead.delete()` faz soft + cascade soft em filhos seguros (Opportunity,
    Proposal não-aceita). Contract.lead é PROTECT (não cascade) — contrato
    assinado preserva o Lead.
    """

    class Source(models.TextChoices):
        SITE = "site", "Site"
        INDICACAO = "indicacao", "Indicação"
        GOOGLE = "google", "Google"
        INSTAGRAM = "instagram", "Instagram"
        WHATSAPP = "whatsapp", "WhatsApp"
        TELEFONE = "telefone", "Telefone"
        OUTRO = "outro", "Outro"

    name = models.CharField("Nome da Oportunidade", max_length=255)
    contato = models.ForeignKey(
        "contacts.Contato",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="leads",
        verbose_name="Contato",
    )
    # DEPRECATED: substituídos por lead.contato.email/phone/company/cpf_cnpj.
    # Mantidos temporariamente para compatibilidade com automation/seed e leads
    # antigos sem contato vinculado. Serão removidos em entrega futura.
    email = models.EmailField("E-mail (legado)", blank=True)
    phone = models.CharField("Telefone (legado)", max_length=20, blank=True)
    company = models.CharField("Empresa (legado)", max_length=255, blank=True)
    cpf = models.CharField(
        "CPF (legado)", max_length=14, blank=True, validators=[validate_cpf]
    )
    cnpj = models.CharField(
        "CNPJ (legado)", max_length=18, blank=True, validators=[validate_cnpj]
    )
    source = models.CharField(
        "Origem",
        max_length=20,
        choices=Source.choices,
        default=Source.OUTRO,
    )
    pipeline_stage = models.ForeignKey(
        "crm.PipelineStage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
        verbose_name="Etapa",
    )
    servico = models.ForeignKey(
        "operations.ServiceType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
        verbose_name="Serviço Cadastrado",
    )
    # RV06 — Valor estimado do negócio. Usado quando Lead vai para etapa
    # de ganho (is_won=True) e não há proposta aceita ainda. Cria
    # FinancialEntry pendente com esse valor (ou cai em servico.default_price).
    estimated_value = models.DecimalField(
        "Valor estimado",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Valor previsto do negócio. Usado para gerar entrada financeira "
            "automática quando o lead vai para uma etapa de ganho sem proposta "
            "aceita. Se vazio, usa o valor padrão do serviço vinculado."
        ),
    )
    notes = models.TextField("Observações", blank=True)
    external_ref = models.CharField(
        "Referência Externa",
        max_length=255,
        blank=True,
        help_text="ID externo (chatbot, API)",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_leads",
        verbose_name="Responsável",
    )

    class Meta:
        verbose_name = "Lead / Oportunidade"
        verbose_name_plural = "Leads / Oportunidades"
        ordering = ["-created_at"]

    def __str__(self):
        if self.contato_id:
            return f"{self.name} — {self.contato.name}"
        return self.name

    @property
    def contact_name(self) -> str:
        """Nome do cliente: prioriza Contato, fallback no campo legado."""
        if self.contato_id:
            return self.contato.name
        return self.name

    @property
    def contact_phone(self) -> str:
        if self.contato_id:
            return self.contato.whatsapp_or_phone or ""
        return self.phone

    @property
    def contact_email(self) -> str:
        if self.contato_id:
            return self.contato.email
        return self.email

    @property
    def contact_document(self) -> str:
        if self.contato_id:
            return self.contato.cpf_cnpj
        return self.cpf or self.cnpj

    def delete(self, using=None, keep_parents=False, hard: bool = False,
               cascade_soft: bool = True):
        """Soft-delete com cascade para filhos seguros.

        Comportamento:
        - `hard=True`: deleção real (Django dispara PROTECT em Contract).
        - `cascade_soft=True` (default): também soft-deleta Opportunities e
          Proposals em estado DRAFT/SENT/VIEWED.
        - **Pré-condição PROTECT**: se houver Contract vinculado, levanta
          `ProtectedError` ANTES do soft-delete. Reflete `Contract.lead =
          PROTECT` para preservação documental (LGPD/fiscal). Sem isso, o
          soft seria silencioso e o lead "sumiria" da UI deixando contratos
          órfãos.
        """
        from django.db.models import ProtectedError

        # Pré-check PROTECT semântico
        contracts = list(self.contracts.all()[:5])
        if contracts:
            raise ProtectedError(
                "Lead vinculado a contrato(s). Exclua/cancele o contrato antes "
                "de remover o lead (preservação documental).",
                set(contracts),
            )

        if hard:
            return super().delete(
                using=using, keep_parents=keep_parents, hard=True,
            )
        if cascade_soft:
            # Opportunities: hard-delete (são derivados, sem soft-delete próprio)
            self.opportunities.all().delete()
            # Proposals em estado pré-aceite: soft-delete cascata
            try:
                from apps.proposals.models import Proposal
                Proposal.all_objects.filter(
                    lead=self,
                    status__in=[
                        Proposal.Status.DRAFT,
                        Proposal.Status.SENT,
                        Proposal.Status.VIEWED,
                    ],
                    deleted_at__isnull=True,
                ).update(deleted_at=timezone.now())
            except ImportError:
                pass
        return super().delete(using=using, keep_parents=keep_parents)


class Pipeline(TenantOwnedModel):
    """Pipeline de vendas configurável por empresa."""

    name = models.CharField("Nome", max_length=100)
    is_default = models.BooleanField("Pipeline padrão", default=False)
    description = models.TextField("Descrição", blank=True)

    class Meta:
        verbose_name = "Pipeline"
        verbose_name_plural = "Pipelines"
        ordering = ["name"]

    def __str__(self):
        return self.name


class PipelineStage(TimestampedModel):
    """Etapa de um pipeline de vendas."""

    pipeline = models.ForeignKey(
        Pipeline,
        on_delete=models.CASCADE,
        related_name="stages",
        verbose_name="Pipeline",
    )
    name = models.CharField("Nome", max_length=100)
    order = models.PositiveIntegerField("Ordem", default=0)
    color = models.CharField("Cor", max_length=7, default="#6366F1")
    is_won = models.BooleanField("Etapa de ganho", default=False)
    is_lost = models.BooleanField("Etapa de perda", default=False)

    class Meta:
        verbose_name = "Etapa do Pipeline"
        verbose_name_plural = "Etapas do Pipeline"
        ordering = ["order"]

    def __str__(self):
        return f"{self.pipeline.name} - {self.name}"


class Opportunity(TenantOwnedModel):
    """Oportunidade de negócio vinculada a um lead."""

    class Priority(models.TextChoices):
        LOW = "low", "Baixa"
        MEDIUM = "medium", "Média"
        HIGH = "high", "Alta"

    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="opportunities",
        verbose_name="Lead",
    )
    pipeline = models.ForeignKey(
        Pipeline,
        on_delete=models.CASCADE,
        related_name="opportunities",
        verbose_name="Pipeline",
    )
    current_stage = models.ForeignKey(
        PipelineStage,
        on_delete=models.PROTECT,
        related_name="opportunities",
        verbose_name="Etapa atual",
    )
    title = models.CharField("Título", max_length=255)
    value = models.DecimalField(
        "Valor",
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    probability = models.PositiveIntegerField("Probabilidade (%)", default=50)
    expected_close_date = models.DateField(
        "Data prevista de fechamento",
        null=True,
        blank=True,
    )
    priority = models.CharField(
        "Prioridade",
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    notes = models.TextField("Observações", blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_opportunities",
        verbose_name="Responsável",
    )
    won_at = models.DateTimeField("Data de ganho", null=True, blank=True)
    lost_at = models.DateTimeField("Data de perda", null=True, blank=True)
    lost_reason = models.TextField("Motivo da perda", blank=True)

    class Meta:
        verbose_name = "Oportunidade"
        verbose_name_plural = "Oportunidades"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["empresa", "current_stage", "won_at"]),
        ]

    def __str__(self):
        return self.title


class LeadContact(TenantOwnedModel):
    """Registro de contato/follow-up com um Lead."""

    class Channel(models.TextChoices):
        PHONE = "phone", "Ligação"
        EMAIL = "email", "E-mail"
        WHATSAPP = "whatsapp", "WhatsApp"
        MEETING = "meeting", "Reunião"
        CHATBOT = "chatbot", "Chatbot"
        OTHER = "other", "Outro"

    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="contacts",
        verbose_name="Lead",
    )
    channel = models.CharField(
        "Canal",
        max_length=20,
        choices=Channel.choices,
        default=Channel.PHONE,
    )
    note = models.TextField("Observação", blank=True)
    contacted_at = models.DateTimeField("Data do contato", default=timezone.now)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lead_contacts",
        verbose_name="Responsável",
    )
    external_ref = models.CharField(
        "Referência externa",
        max_length=255,
        blank=True,
        help_text="ID externo (ex.: chatbot_session_id) para idempotência",
    )

    class Meta:
        verbose_name = "Contato com Lead"
        verbose_name_plural = "Contatos com Leads"
        ordering = ["-contacted_at"]
        indexes = [
            models.Index(fields=["empresa", "lead"]),
            models.Index(fields=["empresa", "channel", "contacted_at"]),
        ]

    def __str__(self):
        return f"{self.lead.name} — {self.get_channel_display()} ({self.contacted_at:%d/%m/%Y %H:%M})"


class LeadTag(TenantOwnedModel):
    """Tag livre aplicada a um Lead (RV06 — automação 'apply_tag').

    Modelo mínimo: nome livre + lead + empresa. Sem cores/categorias por enquanto
    (escopo da iteração V2). Garante unicidade (empresa, lead, name) para evitar
    duplicação quando a action `apply_tag` é executada múltiplas vezes.
    """

    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="tags_applied",
        verbose_name="Lead",
    )
    name = models.CharField("Tag", max_length=40, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lead_tags_created",
        verbose_name="Criado por",
    )

    class Meta:
        verbose_name = "Tag de Lead"
        verbose_name_plural = "Tags de Leads"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "lead", "name"],
                name="crm_leadtag_unique_per_lead",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "name"]),
        ]

    def __str__(self):
        return f"#{self.name} → {self.lead.name}"


class FollowUpSettings(TenantOwnedModel):
    """RV07 (6.2) — Configuração dos lembretes de follow-up de leads.

    Linha com ``user=None`` = padrão da empresa; linha com ``user`` = override
    do usuário. Lembretes são gerados quando um lead fica sem contato por mais
    de N dias (limiares configuráveis).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True, on_delete=models.CASCADE,
        related_name="followup_settings",
        help_text="NULL = padrão da empresa; preenchido = preferência do usuário.",
    )
    enabled = models.BooleanField("Ativo", default=True)
    threshold_1_days = models.PositiveIntegerField("1º lembrete (dias)", default=7)
    threshold_2_days = models.PositiveIntegerField("2º lembrete (dias)", default=14)
    threshold_3_days = models.PositiveIntegerField("3º lembrete (dias)", default=30)
    threshold_4_days = models.PositiveIntegerField("4º lembrete (dias)", default=90)

    class Meta:
        verbose_name = "Configuração de Follow-up"
        verbose_name_plural = "Configurações de Follow-up"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "user"],
                name="uniq_followup_settings_empresa_user",
            ),
            models.UniqueConstraint(
                fields=["empresa"], condition=models.Q(user__isnull=True),
                name="uniq_followup_empresa_default",
            ),
        ]

    def thresholds(self):
        """Limiares positivos, únicos e ordenados (asc)."""
        vals = {
            self.threshold_1_days, self.threshold_2_days,
            self.threshold_3_days, self.threshold_4_days,
        }
        return sorted(d for d in vals if d and d > 0)

    def __str__(self):
        alvo = "empresa" if not self.user_id else f"user {self.user_id}"
        return f"Follow-up {self.empresa_id} ({alvo})"


class LeadFollowUpReminder(TenantOwnedModel):
    """RV07 (6.2) — Marcador de idempotência de follow-up.

    Um lembrete por ``(lead, threshold_days, last_contact_at)``: incluir a base
    de último contato na chave faz o ciclo reiniciar quando há um novo contato
    (a base avança → o mesmo limiar pode disparar de novo no próximo ciclo).
    """

    lead = models.ForeignKey(
        Lead, on_delete=models.CASCADE, related_name="followup_reminders",
    )
    threshold_days = models.PositiveIntegerField()
    last_contact_at = models.DateTimeField()
    notified_at = models.DateTimeField(default=timezone.now)
    notification = models.ForeignKey(
        "communications.Notification",
        null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        verbose_name = "Lembrete de Follow-up"
        verbose_name_plural = "Lembretes de Follow-up"
        constraints = [
            models.UniqueConstraint(
                fields=["lead", "threshold_days", "last_contact_at"],
                name="uniq_followup_lead_threshold_basis",
            ),
        ]
        indexes = [models.Index(fields=["empresa", "lead"])]


def get_effective_followup_settings(empresa, user=None):
    """RV07 (6.2) — Resolve a config de follow-up: override do usuário se
    existir e estiver habilitado, senão o padrão da empresa, senão um default
    em memória (o recurso funciona antes de qualquer config salva)."""
    if user is not None:
        per_user = FollowUpSettings.objects.filter(empresa=empresa, user=user).first()
        if per_user is not None:
            return per_user
    default = FollowUpSettings.objects.filter(
        empresa=empresa, user__isnull=True,
    ).first()
    if default is not None:
        return default
    return FollowUpSettings(empresa=empresa, user=None)


class LeadChecklist(TimestampedModel):
    """RV07 (4.1) — Item de checklist de um Lead.

    Usado sobretudo no pós-venda / execução do serviço (ex.: "Levantamento
    realizado", "Memorial concluído", "Revisão técnica", "Entrega ao cliente").
    Mesmo padrão do WorkOrderChecklist — alcança o tenant via ``lead.empresa``.
    """

    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="checklist_items",
        verbose_name="Lead",
    )
    description = models.CharField("Descrição", max_length=500)
    is_completed = models.BooleanField("Concluído", default=False)
    completed_at = models.DateTimeField("Concluído em", null=True, blank=True)
    order = models.PositiveIntegerField("Ordem", default=0)

    class Meta:
        verbose_name = "Item do Checklist do Lead"
        verbose_name_plural = "Itens do Checklist do Lead"
        ordering = ["order"]

    def __str__(self):
        return self.description
