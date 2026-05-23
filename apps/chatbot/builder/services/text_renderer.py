"""RV06 — Renderização de variáveis em mensagens do chatbot.

Cliente pediu: 'colocar para buscar coisas ja cadastradas no sistema
(tipo nome, qq coisa, no meu caso eu quero q ele busque o serviço q o
cara selecionou)'. Permite escrever no construtor:

    'Perfeito! Você selecionou: {{ servico.name }} por R$ {{ servico.price }}'

E na hora de enviar, vira:

    'Perfeito! Você selecionou: Topografia Premium por R$ 5500.00'

Variáveis disponíveis:
- lead.name, lead.email, lead.phone, lead.company, lead.cpf_cnpj
- servico.name, servico.description, servico.price, servico.prazo_dias,
  servico.id
- empresa.name, empresa.slug, empresa.email, empresa.phone
- data.<qualquer_chave_do_lead_data>  (acesso bruto, ex.: data.servico_id)
- now.date, now.time, now.datetime

Implementação reusa Jinja2 SandboxedEnvironment de communications.
Falha graceful: se variável não existe ou template tem erro, retorna
texto literal — nunca quebra o fluxo.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.chatbot.models import ChatbotSession

logger = logging.getLogger(__name__)


# Lista canônica de variáveis disponíveis — usada pelo frontend para
# popular o dropdown "Inserir variável". Exportada via /api/chatbot/options/template_vars/
AVAILABLE_VARIABLES = [
    {"path": "lead.name", "label": "Nome do lead", "example": "João Silva"},
    {"path": "lead.email", "label": "E-mail do lead", "example": "joao@email.com"},
    {"path": "lead.phone", "label": "Telefone do lead", "example": "(11) 99999-0000"},
    {"path": "lead.company", "label": "Empresa do lead", "example": "Mapper Topografia"},
    {"path": "lead.cpf_cnpj", "label": "CPF/CNPJ do lead", "example": "12.345.678/0001-90"},
    {"path": "servico.name", "label": "Nome do serviço selecionado", "example": "Topografia Premium"},
    {"path": "servico.description", "label": "Descrição do serviço", "example": "Levantamento topográfico…"},
    {"path": "servico.price", "label": "Valor do serviço (R$)", "example": "5500.00"},
    {"path": "servico.prazo_dias", "label": "Prazo do serviço (dias)", "example": "14"},
    {"path": "empresa.name", "label": "Nome da empresa", "example": "Mapper Topografia"},
    {"path": "empresa.email", "label": "E-mail da empresa", "example": "contato@mapper.com"},
    {"path": "empresa.phone", "label": "Telefone da empresa", "example": "(31) 99760-0908"},
    {"path": "now.date", "label": "Data atual", "example": "23/05/2026"},
    {"path": "now.time", "label": "Hora atual", "example": "16:00"},
    {"path": "now.datetime", "label": "Data e hora", "example": "23/05/2026 16:00"},
]


def render_chatbot_text(text: str, session) -> str:
    """Renderiza variáveis Jinja2 em texto de mensagem do chatbot.

    Args:
        text: template raw (ex.: 'Olá {{ lead.name }}, valor R$ {{ servico.price }}')
        session: ChatbotSession (com lead, lead_data, flow.empresa) OU
                 dict no formato sandbox do simulator (state).

    Returns:
        Texto renderizado. Se algo falha, retorna texto original (não quebra fluxo).
    """
    if not text or "{{" not in text:
        return text or ""
    try:
        from apps.communications.templates_service import _get_env
        env = _get_env()
        if env is None:
            return text
        ctx = _build_chatbot_context(session)
        return env.from_string(text).render(**ctx)
    except Exception:  # noqa: BLE001
        logger.exception("render_chatbot_text failed text=%r", text[:80])
        return text


def _build_chatbot_context(session) -> dict:
    """Constrói dict de variáveis para o template.

    Aceita session = ChatbotSession OU dict (state do simulator).
    """
    # Cenário 1: ChatbotSession real (persistido)
    lead_data = {}
    lead = None
    empresa = None
    try:
        from apps.chatbot.models import ChatbotSession
        if isinstance(session, ChatbotSession):
            lead_data = session.lead_data or {}
            lead = session.lead
            empresa = session.flow.empresa if session.flow_id else None
    except Exception:  # noqa: BLE001
        pass

    # Cenário 2: simulator state (dict)
    if isinstance(session, dict):
        lead_data = session.get("lead_data", {}) or {}
        # No simulator não há lead real, só dados em lead_data
        lead = None
        # Empresa pode ser passada externamente — tentamos pegar de session
        empresa = session.get("_empresa")

    # ----- LEAD -----
    lead_ctx = {
        "name": _g(lead, "name") or lead_data.get("name", ""),
        "email": _g(lead, "email") or _g_contato(lead, "email") or lead_data.get("email", ""),
        "phone": _g(lead, "phone") or _g_contato(lead, "phone") or lead_data.get("phone", ""),
        "company": _g(lead, "company") or _g_contato(lead, "company") or lead_data.get("company", ""),
        "cpf_cnpj": _g_contato(lead, "cpf_cnpj") or lead_data.get("cpf_cnpj", ""),
    }

    # ----- SERVICO (via servico_snapshot do lead_data) -----
    snap = lead_data.get("servico_snapshot") or {}
    servico_ctx = {
        "id": snap.get("id", ""),
        "name": snap.get("name", ""),
        "description": snap.get("default_description") or snap.get("description") or "",
        "price": snap.get("default_price", ""),
        "prazo_dias": snap.get("default_prazo_dias", ""),
        "proposal_template_id": snap.get("default_proposal_template_id", ""),
        "contract_template_id": snap.get("default_contract_template_id", ""),
    }

    # ----- EMPRESA -----
    empresa_ctx = {
        "name": _g(empresa, "name"),
        "slug": _g(empresa, "slug"),
        "email": _g(empresa, "email"),
        "phone": _g(empresa, "phone"),
    }

    # ----- NOW -----
    now = datetime.now()
    now_ctx = {
        "date": now.strftime("%d/%m/%Y"),
        "time": now.strftime("%H:%M"),
        "datetime": now.strftime("%d/%m/%Y %H:%M"),
        "year": now.year,
    }

    return {
        "lead": lead_ctx,
        "servico": servico_ctx,
        "empresa": empresa_ctx,
        "now": now_ctx,
        # Acesso bruto ao lead_data — escape hatch para variáveis customizadas
        "data": lead_data,
    }


def _g(obj, attr: str) -> str:
    """Get attr seguro: retorna '' se None ou vazio."""
    if obj is None:
        return ""
    val = getattr(obj, attr, None)
    return str(val) if val is not None else ""


def _g_contato(lead, attr: str) -> str:
    """Get attr do lead.contato (se houver)."""
    if lead is None:
        return ""
    contato = getattr(lead, "contato", None)
    return _g(contato, attr)
