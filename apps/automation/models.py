from django.db import models

from apps.core.models import TenantOwnedModel


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
