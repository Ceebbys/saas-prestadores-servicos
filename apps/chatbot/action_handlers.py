"""Handlers das ações automáticas do chatbot — implementação centralizada.

Compartilhado entre o motor V1 (legacy ChatbotStep + ChatbotAction) e o
motor V2 (graph_json + node `action`). Cada handler:

- Recebe `session: ChatbotSession` + `config: dict` (config do action)
- É **idempotente** quando possível (re-executar não duplica efeitos)
- Retorna `dict` com `{ok: bool, message: str, extra: dict}` para log
- Não levanta exceções: capture + retorne `{ok: False, message: ...}`

Tipos suportados (RV06):
- create_lead          → reusa _create_lead_action
- update_pipeline      → move lead para PipelineStage
- apply_tag            → cria LeadTag
- link_servico         → grava session.lead_data['servico_id']
- register_event       → cria AutomationLog
- send_email           → SMTP do tenant via apps.communications.services.send_email
- send_whatsapp        → Evolution API via apps.chatbot.whatsapp
- send_proposal        → reusa apps.proposals.services.whatsapp.send_proposal_whatsapp
- send_contract        → reusa apps.contracts.services.whatsapp.send_contract_whatsapp
- create_task          → placeholder (V2 — não implementado)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.chatbot.models import ChatbotSession

logger = logging.getLogger(__name__)


def dispatch_action(
    action_type: str,
    session: "ChatbotSession",
    config: dict,
) -> dict:
    """Dispatcher central. Retorna {ok, message, extra}.

    Nunca levanta — captura erros e retorna ok=False.
    """
    handler = _HANDLERS.get(action_type)
    if handler is None:
        logger.warning(
            "dispatch_action: tipo '%s' desconhecido (session=%s)",
            action_type, session.session_key,
        )
        return {
            "ok": False,
            "message": f"Tipo de ação desconhecido: {action_type}",
            "extra": {"unknown": True},
        }
    try:
        return handler(session, config)
    except Exception as exc:  # noqa: BLE001 — handler nunca derruba o fluxo
        logger.exception(
            "dispatch_action: erro em handler '%s' (session=%s)",
            action_type, session.session_key,
        )
        return {
            "ok": False,
            "message": f"Erro executando ação: {exc!r}"[:300],
            "extra": {"exception": True},
        }


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_create_lead(session: "ChatbotSession", config: dict) -> dict:
    """Cria Lead a partir de session.lead_data. Reusa _create_lead_action."""
    # Defensivo: precisa de pelo menos 1 sinal de identificação
    lead_data = session.lead_data or {}
    has_identity = bool(
        lead_data.get("name")
        or lead_data.get("email")
        or lead_data.get("phone")
        or lead_data.get("cpf_cnpj")
    )
    if not has_identity:
        return {
            "ok": False,
            "message": (
                "create_lead pulado: lead_data sem name/email/phone/cpf_cnpj. "
                "Posicione esta ação DEPOIS de pelo menos um Coletar dado ou Pergunta."
            ),
            "extra": {"skipped": True, "reason": "no_identity"},
        }
    from apps.chatbot.services import _create_lead_action
    lead = _create_lead_action(session)
    if lead is None:
        return {
            "ok": False,
            "message": "Falha ao criar Lead — verifique logs",
            "extra": {},
        }
    if session.lead_id != lead.pk:
        session.lead = lead
        session.save(update_fields=["lead", "updated_at"])
    return {
        "ok": True,
        "message": f"Lead #{lead.pk} criado",
        "extra": {"lead_id": lead.pk},
    }


def _handle_link_servico(session: "ChatbotSession", config: dict) -> dict:
    """Grava servico_id em session.lead_data. O create_lead posterior usará.

    Se o lead já existe na session, atualiza Lead.servico imediatamente.
    """
    from apps.operations.models import ServiceType

    raw_id = config.get("servico_id")
    if not raw_id:
        return {
            "ok": False,
            "message": "Vincular serviço: servico_id ausente",
            "extra": {"skipped": True, "reason": "missing_servico_id"},
        }
    try:
        servico_id = int(raw_id)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "message": f"servico_id inválido: {raw_id!r}",
            "extra": {"skipped": True, "reason": "invalid_servico_id"},
        }

    empresa = session.flow.empresa
    servico = ServiceType.objects.filter(
        pk=servico_id, empresa=empresa, is_active=True,
    ).first()
    if servico is None:
        return {
            "ok": False,
            "message": f"Serviço #{servico_id} não encontrado nesta empresa",
            "extra": {"skipped": True, "reason": "not_found"},
        }

    # Grava em session.lead_data (usado por create_lead_from_chatbot)
    lead_data = dict(session.lead_data or {})
    lead_data["servico_id"] = servico.pk
    # Snapshot dos campos do serviço (útil para próximas ações: send_proposal)
    lead_data["servico_snapshot"] = {
        "id": servico.pk,
        "name": servico.name,
        "default_price": str(servico.default_price),
        "default_prazo_dias": servico.default_prazo_dias,
        "default_proposal_template_id": servico.default_proposal_template_id,
        "default_contract_template_id": servico.default_contract_template_id,
    }
    session.lead_data = lead_data
    session.save(update_fields=["lead_data", "updated_at"])

    # Se já tem Lead criado, atualiza FK imediato
    if session.lead_id and session.lead.servico_id != servico.pk:
        session.lead.servico = servico
        # Etapa de pipeline default do serviço (se existe)
        if servico.default_stage_id and not session.lead.pipeline_stage_id:
            session.lead.pipeline_stage_id = servico.default_stage_id
        session.lead.save(update_fields=[
            "servico", "pipeline_stage", "updated_at",
        ])

    return {
        "ok": True,
        "message": f"Serviço '{servico.name}' vinculado",
        "extra": {
            "servico_id": servico.pk,
            "servico_name": servico.name,
            "lead_already_existed": bool(session.lead_id),
        },
    }


def _handle_update_pipeline(session: "ChatbotSession", config: dict) -> dict:
    """Move Lead da session para a PipelineStage configurada."""
    from apps.crm.models import PipelineStage

    raw_stage = config.get("pipeline_stage_id")
    if not raw_stage:
        return {
            "ok": False,
            "message": "Atualizar pipeline: pipeline_stage_id ausente",
            "extra": {"skipped": True},
        }
    try:
        stage_id = int(raw_stage)
    except (TypeError, ValueError):
        return {"ok": False, "message": f"pipeline_stage_id inválido: {raw_stage!r}", "extra": {}}

    if not session.lead_id:
        return {
            "ok": False,
            "message": "Lead ainda não criado — posicione esta ação após 'Criar lead'",
            "extra": {"skipped": True, "reason": "no_lead"},
        }

    empresa = session.flow.empresa
    stage = PipelineStage.objects.filter(
        pk=stage_id, pipeline__empresa=empresa,
    ).first()
    if stage is None:
        return {
            "ok": False,
            "message": f"Etapa #{stage_id} não encontrada nesta empresa",
            "extra": {"skipped": True},
        }
    session.lead.pipeline_stage = stage
    session.lead.save(update_fields=["pipeline_stage", "updated_at"])
    return {
        "ok": True,
        "message": f"Lead movido para '{stage.name}'",
        "extra": {"stage_id": stage.pk, "stage_name": stage.name},
    }


def _handle_apply_tag(session: "ChatbotSession", config: dict) -> dict:
    """Cria LeadTag para o lead da session."""
    from apps.crm.models import LeadTag

    tag_name = (config.get("tag_name") or "").strip()
    if not tag_name:
        return {"ok": False, "message": "apply_tag: tag_name vazio", "extra": {}}
    if not session.lead_id:
        return {
            "ok": False,
            "message": "Lead ainda não criado — posicione esta ação após 'Criar lead'",
            "extra": {"skipped": True, "reason": "no_lead"},
        }
    # Idempotência: não duplica
    tag, created = LeadTag.objects.get_or_create(
        empresa=session.flow.empresa,
        lead=session.lead,
        name=tag_name,
    )
    return {
        "ok": True,
        "message": f"Tag '{tag_name}' {'aplicada' if created else 'já presente'}",
        "extra": {"tag_id": tag.pk, "created": created},
    }


def _handle_register_event(session: "ChatbotSession", config: dict) -> dict:
    """Registra evento no AutomationLog (audit trail)."""
    from apps.automation.models import AutomationLog

    event_name = (config.get("event_name") or "").strip()
    if not event_name:
        return {"ok": False, "message": "register_event: event_name vazio", "extra": {}}

    AutomationLog.objects.create(
        empresa=session.flow.empresa,
        action=AutomationLog.Action.CHATBOT_TO_LEAD,
        entity_type="chatbot_session",
        entity_id=session.pk,
        source_entity_type="chatbot_flow",
        source_entity_id=session.flow_id,
        metadata={
            "event_name": event_name,
            "session_key": str(session.session_key),
            "extra": config.get("event_data") or {},
        },
    )
    return {
        "ok": True,
        "message": f"Evento '{event_name}' registrado",
        "extra": {"event_name": event_name},
    }


def _handle_send_email(session: "ChatbotSession", config: dict) -> dict:
    """Envia e-mail via SMTP do tenant. Suporta placeholders Jinja2."""
    from apps.communications.services import send_email
    from apps.communications.models import get_or_create_conversation
    from apps.communications.templates_service import _build_context, _get_env

    to_kind = config.get("to") or "lead"
    subject = (config.get("subject") or "").strip()
    body = (config.get("body") or "").strip()
    if not subject or not body:
        return {"ok": False, "message": "send_email: subject ou body vazio", "extra": {}}

    # Resolve destinatário
    to_email = ""
    if to_kind == "lead":
        if not session.lead_id:
            return {
                "ok": False,
                "message": "send_email to=lead mas Lead ainda não criado",
                "extra": {"skipped": True, "reason": "no_lead"},
            }
        contato = getattr(session.lead, "contato", None)
        to_email = (contato.email if contato else "") or session.lead.email or ""
    elif to_kind == "admin":
        to_email = (session.flow.empresa.email or "").strip()
    elif to_kind == "custom":
        to_email = (config.get("to_custom") or "").strip()

    if not to_email:
        return {
            "ok": False,
            "message": f"send_email to={to_kind}: e-mail destinatário não disponível",
            "extra": {"skipped": True, "reason": "no_email"},
        }

    # Renderiza templates Jinja2 (subject + body)
    env = _get_env()
    ctx = _build_context(
        empresa=session.flow.empresa,
        # Cria conversation só pro context se houver lead
    )
    if session.lead_id:
        try:
            conv = get_or_create_conversation(session.flow.empresa, session.lead)
            ctx = _build_context(
                conversation=conv,
                empresa=session.flow.empresa,
            )
        except Exception:  # noqa: BLE001
            pass

    try:
        rendered_subject = env.from_string(subject).render(**ctx) if env else subject
        rendered_body = env.from_string(body).render(**ctx) if env else body
    except Exception:  # noqa: BLE001
        rendered_subject = subject
        rendered_body = body

    # Para enviar email pela inbox, precisa de Conversation. Se há lead → conv;
    # senão envia direto via Django mail
    if session.lead_id:
        conv = get_or_create_conversation(session.flow.empresa, session.lead)
        msg = send_email(conv, rendered_subject, rendered_body, to_email=to_email)
        if msg.delivery_status == "failed":
            return {
                "ok": False,
                "message": f"Falha SMTP: {msg.error_message}",
                "extra": {"message_id": msg.pk},
            }
        return {
            "ok": True,
            "message": f"E-mail enviado para {to_email}",
            "extra": {"message_id": msg.pk, "to": to_email},
        }
    else:
        # Sem lead → enviar via Django mail direto (não grava na inbox)
        from django.core.mail import EmailMessage
        from apps.proposals.services.email import _resolve_smtp_for
        try:
            connection, from_address = _resolve_smtp_for(session.flow.empresa)
            EmailMessage(
                subject=rendered_subject,
                body=rendered_body,
                from_email=from_address,
                to=[to_email],
                connection=connection,
            ).send(fail_silently=False)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"Falha SMTP: {exc!r}"[:300], "extra": {}}
        return {
            "ok": True,
            "message": f"E-mail enviado para {to_email} (sem inbox)",
            "extra": {"to": to_email},
        }


def _handle_send_whatsapp(session: "ChatbotSession", config: dict) -> dict:
    """Envia WhatsApp via Evolution API. Suporta placeholders Jinja2."""
    from apps.chatbot.models import WhatsAppConfig
    from apps.chatbot.whatsapp import EvolutionAPIClient
    from apps.communications.templates_service import _build_context, _get_env
    from apps.communications.models import get_or_create_conversation
    from apps.communications.services import record_bot_outbound

    text = (config.get("text") or "").strip()
    if not text:
        return {"ok": False, "message": "send_whatsapp: text vazio", "extra": {}}
    if not session.lead_id:
        return {
            "ok": False,
            "message": "send_whatsapp: Lead ainda não criado",
            "extra": {"skipped": True, "reason": "no_lead"},
        }

    contato = getattr(session.lead, "contato", None)
    phone = (
        (contato.whatsapp or contato.phone if contato else "")
        or session.lead.phone
        or session.sender_id
        or ""
    )
    phone_digits = "".join(c for c in phone if c.isdigit())
    if not phone_digits:
        return {
            "ok": False,
            "message": "send_whatsapp: telefone do lead não disponível",
            "extra": {"skipped": True, "reason": "no_phone"},
        }

    empresa = session.flow.empresa
    cfg = WhatsAppConfig.objects.filter(empresa=empresa).first()
    if not cfg:
        return {
            "ok": False,
            "message": "WhatsApp não configurado para esta empresa",
            "extra": {"skipped": True, "reason": "no_whatsapp_config"},
        }

    # Renderiza Jinja2
    env = _get_env()
    try:
        conv = get_or_create_conversation(empresa, session.lead)
        ctx = _build_context(conversation=conv, empresa=empresa)
        rendered = env.from_string(text).render(**ctx) if env else text
    except Exception:  # noqa: BLE001
        rendered = text
        conv = None

    client = EvolutionAPIClient(
        api_url=cfg.effective_api_url,
        api_key=cfg.effective_instance_key,
        instance=cfg.instance_name,
    )
    if not client.configured:
        return {
            "ok": False,
            "message": "Evolution API não configurada",
            "extra": {"skipped": True, "reason": "evolution_not_configured"},
        }
    try:
        ok = client.send_text(phone_digits, rendered)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"Erro Evolution: {exc!r}"[:300], "extra": {}}

    if ok and conv is not None:
        # Registra como bot outbound na inbox
        try:
            record_bot_outbound(
                empresa=empresa, lead=session.lead,
                channel="whatsapp", content=rendered,
                chatbot_session=session,
            )
        except Exception:  # noqa: BLE001
            logger.exception("send_whatsapp: falha gravando outbound na inbox")

    return {
        "ok": ok,
        "message": (
            f"WhatsApp enviado para {phone_digits}" if ok
            else f"Falha ao enviar WhatsApp para {phone_digits}"
        ),
        "extra": {"phone": phone_digits, "rendered_len": len(rendered)},
    }


def _handle_send_proposal(session: "ChatbotSession", config: dict) -> dict:
    """Envia proposta por WhatsApp. Cria nova proposta se não existe."""
    from apps.proposals.models import Proposal
    from apps.proposals.services.whatsapp import send_proposal_whatsapp

    if not session.lead_id:
        return {
            "ok": False,
            "message": "send_proposal: Lead ainda não criado",
            "extra": {"skipped": True, "reason": "no_lead"},
        }

    empresa = session.flow.empresa
    # Busca proposta DRAFT do lead (idempotência)
    proposal = (
        Proposal.objects
        .filter(empresa=empresa, lead=session.lead)
        .order_by("-created_at")
        .first()
    )

    auto_create = config.get("auto_create_if_missing", True)
    if proposal is None and auto_create:
        # Cria nova via template
        template_id = config.get("proposal_template_id")
        proposal = _create_proposal_from_template(
            empresa, session.lead, template_id, session.lead_data,
        )
        if proposal is None:
            return {
                "ok": False,
                "message": "Falha ao criar proposta automaticamente",
                "extra": {"skipped": True},
            }

    if proposal is None:
        return {
            "ok": False,
            "message": "Nenhuma proposta encontrada e auto_create=False",
            "extra": {"skipped": True, "reason": "no_proposal"},
        }

    # Resolve phone
    contato = getattr(session.lead, "contato", None)
    phone = (
        (contato.whatsapp or contato.phone if contato else "")
        or session.lead.phone
        or session.sender_id
        or ""
    )
    if not phone:
        return {
            "ok": False,
            "message": "send_proposal: telefone do lead não disponível",
            "extra": {"skipped": True, "reason": "no_phone"},
        }

    ok, mode, msg = send_proposal_whatsapp(proposal, to_phone=phone)
    return {
        "ok": ok,
        "message": f"send_proposal: {msg}",
        "extra": {"proposal_id": proposal.pk, "mode": mode},
    }


def _handle_send_contract(session: "ChatbotSession", config: dict) -> dict:
    """Envia contrato por WhatsApp. Cria novo se não existe."""
    from apps.contracts.models import Contract
    from apps.contracts.services.whatsapp import send_contract_whatsapp

    if not session.lead_id:
        return {
            "ok": False,
            "message": "send_contract: Lead ainda não criado",
            "extra": {"skipped": True, "reason": "no_lead"},
        }

    empresa = session.flow.empresa
    contract = (
        Contract.objects
        .filter(empresa=empresa, lead=session.lead)
        .order_by("-created_at")
        .first()
    )

    auto_create = config.get("auto_create_if_missing", True)
    if contract is None and auto_create:
        template_id = config.get("contract_template_id")
        contract = _create_contract_from_template(
            empresa, session.lead, template_id, session.lead_data,
        )
        if contract is None:
            return {
                "ok": False,
                "message": "Falha ao criar contrato automaticamente",
                "extra": {"skipped": True},
            }

    if contract is None:
        return {
            "ok": False,
            "message": "Nenhum contrato encontrado e auto_create=False",
            "extra": {"skipped": True, "reason": "no_contract"},
        }

    contato = getattr(session.lead, "contato", None)
    phone = (
        (contato.whatsapp or contato.phone if contato else "")
        or session.lead.phone
        or session.sender_id
        or ""
    )
    if not phone:
        return {
            "ok": False,
            "message": "send_contract: telefone do lead não disponível",
            "extra": {"skipped": True, "reason": "no_phone"},
        }

    ok, mode, msg = send_contract_whatsapp(contract, to_phone=phone)
    return {
        "ok": ok,
        "message": f"send_contract: {msg}",
        "extra": {"contract_id": contract.pk, "mode": mode},
    }


def _handle_create_task(session: "ChatbotSession", config: dict) -> dict:
    """Placeholder — Task não implementado (V2)."""
    logger.info(
        "create_task ainda não implementado (session=%s, config=%s)",
        session.session_key, list(config.keys()),
    )
    return {
        "ok": False,
        "message": "create_task ainda não implementado (disponível em versão futura)",
        "extra": {"not_implemented": True},
    }


# ---------------------------------------------------------------------------
# Helpers internos para criar proposta/contrato a partir de template
# ---------------------------------------------------------------------------


def _create_proposal_from_template(empresa, lead, template_id, lead_data):
    """Cria uma Proposal DRAFT vinculada ao lead, opcionalmente usando template.

    Se template_id não fornecido, tenta:
    1. Template do serviço vinculado (lead_data.servico_snapshot)
    2. Template default da empresa (ProposalTemplate.is_default=True)
    """
    from apps.proposals.models import Proposal, ProposalTemplate

    template = None
    if template_id:
        try:
            template = ProposalTemplate.objects.get(pk=int(template_id), empresa=empresa)
        except (TypeError, ValueError, ProposalTemplate.DoesNotExist):
            template = None
    if template is None:
        # Tenta via serviço
        servico_snap = (lead_data or {}).get("servico_snapshot") or {}
        sid = servico_snap.get("default_proposal_template_id")
        if sid:
            template = ProposalTemplate.objects.filter(pk=sid, empresa=empresa).first()
    if template is None:
        template = ProposalTemplate.objects.filter(
            empresa=empresa, is_default=True,
        ).first()

    intro = ""
    terms = ""
    content = ""
    if template:
        intro = template.introduction or ""
        terms = template.terms or ""
        content = template.content or ""

    proposal = Proposal.objects.create(
        empresa=empresa,
        lead=lead,
        title=f"Proposta — {lead.name}",
        introduction=intro,
        terms=terms,
        content=content,
        status=Proposal.Status.DRAFT,
    )
    logger.info(
        "Proposta #%s criada automaticamente para lead=%s (template=%s)",
        proposal.pk, lead.pk, template.pk if template else None,
    )
    return proposal


def _create_contract_from_template(empresa, lead, template_id, lead_data):
    """Cria um Contract DRAFT vinculado ao lead, opcionalmente usando template."""
    from apps.contracts.models import Contract, ContractTemplate

    template = None
    if template_id:
        try:
            template = ContractTemplate.objects.get(pk=int(template_id), empresa=empresa)
        except (TypeError, ValueError, ContractTemplate.DoesNotExist):
            template = None
    if template is None:
        servico_snap = (lead_data or {}).get("servico_snapshot") or {}
        sid = servico_snap.get("default_contract_template_id")
        if sid:
            template = ContractTemplate.objects.filter(pk=sid, empresa=empresa).first()
    if template is None:
        template = ContractTemplate.objects.filter(
            empresa=empresa, is_default=True,
        ).first()

    content = template.content if template else ""
    contract = Contract.objects.create(
        empresa=empresa,
        lead=lead,
        title=f"Contrato — {lead.name}",
        content=content,
        status=Contract.Status.DRAFT,
    )
    logger.info(
        "Contrato #%s criado automaticamente para lead=%s (template=%s)",
        contract.pk, lead.pk, template.pk if template else None,
    )
    return contract


# ---------------------------------------------------------------------------
# Tabela de despacho
# ---------------------------------------------------------------------------

_HANDLERS = {
    "create_lead": _handle_create_lead,
    "link_servico": _handle_link_servico,
    "update_pipeline": _handle_update_pipeline,
    "apply_tag": _handle_apply_tag,
    "register_event": _handle_register_event,
    "send_email": _handle_send_email,
    "send_whatsapp": _handle_send_whatsapp,
    "send_proposal": _handle_send_proposal,
    "send_contract": _handle_send_contract,
    "create_task": _handle_create_task,
}
