from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TenantOwnedModel


class PipelineAutomationRule(TenantOwnedModel):
    """Regra configurável: evento de proposta → mover lead para etapa do pipeline.

    O usuário (cliente final do SaaS) configura quais eventos disparam quais
    movimentações. Etapas são FK — não há nomes hardcoded ('Negociação',
    'Fechado-Ganho', etc.). Se a etapa for deletada, a regra fica inativa.
    """

    class Event(models.TextChoices):
        PROPOSTA_CRIADA = "proposta_criada", "Proposta criada"
        PROPOSTA_ENVIADA = "proposta_enviada", "Proposta enviada"
        PROPOSTA_ACEITA = "proposta_aceita", "Proposta aceita"
        PROPOSTA_REJEITADA = "proposta_rejeitada", "Proposta rejeitada"
        PROPOSTA_CANCELADA = "proposta_cancelada", "Proposta cancelada"
        PROPOSTA_EXPIRADA = "proposta_expirada", "Proposta expirada"

    name = models.CharField("Nome", max_length=120)
    event = models.CharField(
        "Evento",
        max_length=40,
        choices=Event.choices,
        db_index=True,
    )
    target_pipeline = models.ForeignKey(
        "crm.Pipeline",
        on_delete=models.PROTECT,
        related_name="automation_rules",
        verbose_name="Pipeline destino",
    )
    target_stage = models.ForeignKey(
        "crm.PipelineStage",
        on_delete=models.PROTECT,
        related_name="automation_rules",
        verbose_name="Etapa destino",
    )
    is_active = models.BooleanField("Ativa", default=True, db_index=True)
    priority = models.PositiveIntegerField(
        "Prioridade",
        default=100,
        help_text="Menor valor = maior prioridade. Empate vai por nome.",
    )
    notes = models.TextField("Observações", blank=True)

    class Meta:
        verbose_name = "Regra de Automação"
        verbose_name_plural = "Regras de Automação"
        ordering = ["priority", "name"]
        indexes = [
            models.Index(fields=["empresa", "event", "is_active", "priority"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_event_display()})"

    def clean(self):
        if self.target_stage_id and self.target_pipeline_id:
            stage = self.target_stage
            if stage.pipeline_id != self.target_pipeline_id:
                raise ValidationError({
                    "target_stage": (
                        "A etapa selecionada não pertence ao pipeline escolhido."
                    ),
                })


class AutomationLog(TenantOwnedModel):
    """Registro de cada passo automatizado do pipeline.

    Rastreia a criação automática de entidades (Lead, Proposta, Contrato,
    OS, Financeiro) com referência à entidade de origem, permitindo
    auditoria completa do fluxo de automação.
    """

    class EntityType(models.TextChoices):
        LEAD = "lead", "Lead"
        PROPOSAL = "proposal", "Proposta"
        CONTRACT = "contract", "Contrato"
        WORK_ORDER = "work_order", "Ordem de Serviço"
        FINANCIAL_ENTRY = "financial_entry", "Lançamento Financeiro"

    class Action(models.TextChoices):
        CHATBOT_TO_LEAD = "chatbot_to_lead", "Chatbot → Lead"
        LEAD_TO_PROPOSAL = "lead_to_proposal", "Lead → Proposta"
        PROPOSAL_TO_CONTRACT = "proposal_to_contract", "Proposta → Contrato"
        CONTRACT_TO_WORK_ORDER = "contract_to_work_order", "Contrato → OS"
        WORK_ORDER_TO_BILLING = "work_order_to_billing", "OS → Financeiro"
        FULL_PIPELINE = "full_pipeline", "Pipeline Completo"
        PROPOSAL_PIPELINE_TRIGGER = (
            "proposal_pipeline_trigger", "Proposta → Pipeline (regra)",
        )
        PROPOSAL_DELETED = "proposal_deleted", "Proposta excluída"

    class Status(models.TextChoices):
        SUCCESS = "success", "Sucesso"
        ERROR = "error", "Erro"

    entity_type = models.CharField(max_length=30, choices=EntityType.choices)
    entity_id = models.PositiveIntegerField()
    action = models.CharField(max_length=40, choices=Action.choices)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.SUCCESS,
    )
    source_entity_type = models.CharField(max_length=30, blank=True)
    source_entity_id = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Log de Automação"
        verbose_name_plural = "Logs de Automação"
        indexes = [
            models.Index(fields=["empresa", "action"]),
            models.Index(fields=["empresa", "entity_type", "entity_id"]),
        ]

    def __str__(self):
        return (
            f"{self.get_action_display()} → "
            f"{self.entity_type}#{self.entity_id} ({self.status})"
        )
