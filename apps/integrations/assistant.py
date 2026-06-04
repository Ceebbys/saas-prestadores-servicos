"""RV07 (6.1) — Assistente IA (Claude) para atendimento por WhatsApp.

Recebe a mensagem do cliente + histórico da conversa, conversa com o Claude
(via apps.integrations.llm) com duas ferramentas — salvar dados do lead e criar
proposta (rascunho) — e devolve a resposta para enviar no WhatsApp.

Segurança de negócio: a proposta é criada como RASCUNHO (não envia sozinha);
um humano revisa e envia. Tudo escopado pela empresa do AssistantConfig.
"""
from __future__ import annotations

import logging

from .llm import run_agentic_loop
from .models import AssistantConfig

logger = logging.getLogger(__name__)

_HISTORY_LIMIT = 20  # últimas N mensagens da conversa como contexto


_TOOLS = [
    {
        "name": "save_lead_details",
        "description": (
            "Salva/atualiza os dados do cliente (lead) quando você descobrir o "
            "nome, e-mail ou qual serviço ele quer. Chame assim que tiver "
            "informação nova e relevante — não espere o fim da conversa."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do cliente"},
                "email": {"type": "string", "description": "E-mail do cliente"},
                "interest": {
                    "type": "string",
                    "description": "Serviço/produto de interesse, em poucas palavras",
                },
                "notes": {"type": "string", "description": "Observações úteis da conversa"},
            },
        },
    },
    {
        "name": "create_proposal",
        "description": (
            "Cria uma proposta comercial EM RASCUNHO para o cliente. Use quando "
            "ele demonstrar interesse claro e você tiver o que propor. A proposta "
            "NÃO é enviada automaticamente — fica como rascunho para um humano da "
            "empresa revisar e enviar. Avise o cliente que a proposta será "
            "preparada e enviada em seguida."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título curto da proposta"},
                "description": {
                    "type": "string", "description": "Descrição do serviço proposto",
                },
                "value": {
                    "type": "number",
                    "description": "Valor total estimado em reais, se você souber",
                },
            },
            "required": ["title"],
        },
    },
]


class AssistantService:
    """Assistente IA de um tenant. Criado por ``get_assistant_service``."""

    def __init__(self, config: AssistantConfig):
        self.config = config

    # -- system prompt -------------------------------------------------------
    def _build_system(self, empresa, lead) -> str:
        nome = getattr(empresa, "name", "") or "a empresa"
        base = (
            f"Você é o assistente virtual de atendimento da empresa {nome}, "
            "respondendo clientes pelo WhatsApp em português do Brasil. Seja "
            "cordial, objetivo e use mensagens curtas (estilo WhatsApp, sem "
            "textão). Seu objetivo: entender o que o cliente precisa, "
            "qualificá-lo (nome e qual serviço/interesse) e, quando fizer "
            "sentido, registrar os dados com a ferramenta save_lead_details e "
            "preparar uma proposta com create_proposal. Nunca invente preços ou "
            "prazos que você não tem certeza — se faltar informação, pergunte. "
            "Não prometa nada que dependa de aprovação humana; diga que vai "
            "verificar e retornar."
        )
        custom = (self.config.system_prompt or "").strip()
        if custom:
            base += "\n\nInstruções específicas da empresa:\n" + custom
        if lead is not None and getattr(lead, "name", ""):
            base += f"\n\n(Contexto: cliente já cadastrado como lead — nome: {lead.name}.)"
        return base

    # -- histórico -----------------------------------------------------------
    def _history_from_conversation(self, conversation) -> list[dict]:
        if conversation is None:
            return []
        from apps.communications.models import ConversationMessage

        rows = list(
            ConversationMessage.objects.filter(conversation=conversation)
            .order_by("-created_at")[:_HISTORY_LIMIT]
        )
        history = []
        for m in reversed(rows):
            content = (m.content or "").strip()
            if not content:
                continue
            role = (
                "user"
                if m.direction == ConversationMessage.Direction.INBOUND
                else "assistant"
            )
            history.append({"role": role, "content": content})
        return history

    # -- ferramentas ---------------------------------------------------------
    def _make_executor(self, empresa, lead):
        def executor(name: str, args: dict) -> dict:
            if name == "save_lead_details":
                return self._tool_save_lead(empresa, lead, args)
            if name == "create_proposal":
                return self._tool_create_proposal(empresa, lead, args)
            return {"ok": False, "message": f"ferramenta desconhecida: {name}"}

        return executor

    def _tool_save_lead(self, empresa, lead, args: dict) -> dict:
        if lead is None or getattr(lead, "empresa_id", None) != empresa.pk:
            return {"ok": False, "message": "Lead indisponível para esta conversa."}
        fields = []
        name = (args.get("name") or "").strip()
        if name and (not lead.name or lead.name.lower().startswith("whatsapp")):
            lead.name = name[:255]
            fields.append("name")
        email = (args.get("email") or "").strip()
        if email and not lead.email:
            lead.email = email[:254]
            fields.append("email")
        extra = " ".join(
            p for p in [args.get("interest"), args.get("notes")] if (p or "").strip()
        ).strip()
        if extra:
            prefix = (lead.notes + "\n") if lead.notes else ""
            lead.notes = (prefix + extra)[:2000]
            fields.append("notes")
        if fields:
            fields.append("updated_at")
            lead.save(update_fields=fields)
        return {"ok": True, "message": "Dados do lead atualizados."}

    def _tool_create_proposal(self, empresa, lead, args: dict) -> dict:
        if lead is None or getattr(lead, "empresa_id", None) != empresa.pk:
            return {"ok": False, "message": "Lead indisponível para criar proposta."}
        from apps.automation.services import create_proposal_from_lead

        items_data = None
        value = args.get("value")
        if value:
            try:
                items_data = [{
                    "description": (args.get("title") or "Serviço")[:255],
                    "quantity": 1, "unit_price": float(value),
                }]
            except (TypeError, ValueError):
                items_data = None
        try:
            proposal = create_proposal_from_lead(empresa, lead, items_data=items_data)
        except Exception:  # noqa: BLE001
            logger.exception("assistant: create_proposal_from_lead falhou")
            return {"ok": False, "message": "Não consegui gerar a proposta agora."}

        title = (args.get("title") or "").strip()
        if title and proposal.title != title:
            proposal.title = title[:255]
            proposal.save(update_fields=["title", "updated_at"])
        return {
            "ok": True,
            "message": f"Proposta {proposal.number} criada em rascunho.",
        }

    # -- entrada principal ---------------------------------------------------
    def handle_inbound_message(
        self, *, sender, text, lead=None, conversation=None, history=None, **kwargs
    ) -> dict:
        """Processa uma mensagem do cliente e devolve ``{status, reply, actions}``.

        ``status``: "ok" | "error" | "disabled". ``reply`` é o texto a enviar no
        WhatsApp (vazio em erro — o caller decide o fallback).
        """
        empresa = self.config.empresa
        messages = (
            self._history_from_conversation(conversation)
            if history is None else list(history)
        )
        messages.append({"role": "user", "content": (text or "").strip() or "Olá"})
        # A API exige que a 1ª mensagem seja do usuário.
        while messages and messages[0].get("role") != "user":
            messages.pop(0)

        result = run_agentic_loop(
            api_key=self.config.get_api_key(),
            model=self.config.model_name,
            system=self._build_system(empresa, lead),
            tools=_TOOLS,
            messages=messages,
            tool_executor=self._make_executor(empresa, lead),
        )
        if result.get("error"):
            return {
                "status": "error", "reply": "",
                "error": result["error"], "actions": result.get("actions", []),
            }
        return {
            "status": "ok",
            "reply": result.get("reply", ""),
            "actions": result.get("actions", []),
        }


def get_assistant_service(empresa) -> AssistantService | None:
    config = AssistantConfig.objects.filter(empresa=empresa, is_enabled=True).first()
    return AssistantService(config) if config else None
