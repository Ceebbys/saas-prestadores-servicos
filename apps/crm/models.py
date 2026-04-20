from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TenantOwnedModel, TimestampedModel
from apps.core.validators import validate_cnpj, validate_cpf


class Lead(TenantOwnedModel):
    """Potencial cliente captado pelo CRM."""

    class Source(models.TextChoices):
        SITE = "site", "Site"
        INDICACAO = "indicacao", "Indicação"
        GOOGLE = "google", "Google"
        INSTAGRAM = "instagram", "Instagram"
        WHATSAPP = "whatsapp", "WhatsApp"
        TELEFONE = "telefone", "Telefone"
        OUTRO = "outro", "Outro"

    name = models.CharField("Nome", max_length=255)
    email = models.EmailField("E-mail", blank=True)
    phone = models.CharField("Telefone", max_length=20, blank=True)
    company = models.CharField("Empresa", max_length=255, blank=True)
    cpf = models.CharField(
        "CPF", max_length=14, blank=True, validators=[validate_cpf]
    )
    cnpj = models.CharField(
        "CNPJ", max_length=18, blank=True, validators=[validate_cnpj]
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
        verbose_name = "Lead"
        verbose_name_plural = "Leads"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "cpf"],
                condition=~Q(cpf=""),
                name="unique_cpf_per_empresa",
            ),
            models.UniqueConstraint(
                fields=["empresa", "cnpj"],
                condition=~Q(cnpj=""),
                name="unique_cnpj_per_empresa",
            ),
        ]

    def __str__(self):
        return self.name


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
