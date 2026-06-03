"""SCAFFOLD (Epic 6.1) — Assistente IA estilo LuzIA. Sem chamadas a LLM.

Numa rodada futura, ``handle_inbound_message`` conterá o loop agêntico que cria
leads/propostas/contratos e atualiza o pipeline a partir de mensagens WhatsApp.
"""
from __future__ import annotations

from .models import AssistantConfig


class AssistantService:
    """Esqueleto do assistente. Dormiente neste round."""

    def __init__(self, config: AssistantConfig):
        self.config = config

    def handle_inbound_message(self, *, sender, text, **kwargs) -> dict:
        # STUB: futuro → intenção → criar lead/proposta/contrato, mover pipeline.
        return {"status": "not_configured", "integration_ready": False, "reply": ""}


def get_assistant_service(empresa) -> AssistantService | None:
    config = AssistantConfig.objects.filter(empresa=empresa, is_enabled=True).first()
    return AssistantService(config) if config else None
