"""RV07 (6.2) — Disparo de notificações de eventos de pipeline/operacional.

Centraliza a resolução de destinatários + as chamadas a ``notify()``,
espelhando o padrão de ``_notify_lead_won`` (finance/services.py). Todas as
emissões são best-effort (uma falha não derruba o save que as originou) e
adiadas para ``transaction.on_commit`` (um save revertido não emite nada).

Para silenciar em lote (seeds, simulações), basta setar
``obj._suppress_notification = True`` no objeto de origem.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.urls import reverse

from apps.communications.models import Notification
from apps.communications.notifications import notify

logger = logging.getLogger(__name__)


def _safe_reverse(name, *args):
    try:
        return reverse(name, args=args)
    except Exception:  # noqa: BLE001
        return ""


def _active_member_users(empresa):
    from django.contrib.auth import get_user_model

    from apps.accounts.models import Membership

    ids = Membership.objects.filter(
        empresa=empresa, is_active=True,
    ).values_list("user_id", flat=True)
    return list(get_user_model().objects.filter(pk__in=ids, is_active=True))


def _resolve_recipients(empresa, lead=None, *, extra_user=None):
    """assigned_to (do lead) + extra_user, mas APENAS se forem membros ATIVOS
    da empresa (defesa cross-tenant — um usuário removido da empresa mas ainda
    setado como assigned_to não deve continuar recebendo). Se ninguém
    qualificar, cai para todos os membros ativos."""
    members = {u.pk: u for u in _active_member_users(empresa)}
    users = {}
    if extra_user is not None and extra_user.pk in members:
        users[extra_user.pk] = members[extra_user.pk]
    if lead is not None and getattr(lead, "assigned_to_id", None) in members:
        uid = lead.assigned_to_id
        users[uid] = members[uid]
    if not users:
        users = dict(members)
    return list(users.values())


def _emit(source, empresa, *, type, title, body, icon, url, payload,
          lead=None, extra_user=None):
    if getattr(source, "_suppress_notification", False) or empresa is None:
        return

    def _run():
        try:
            for user in _resolve_recipients(empresa, lead, extra_user=extra_user):
                notify(
                    user, type=type, title=title, body=body, url=url,
                    icon=icon, empresa=empresa, payload=payload,
                )
        except Exception:  # noqa: BLE001
            logger.exception("notify_event_failed type=%s", type)

    transaction.on_commit(_run)


# --- Propostas ---------------------------------------------------------------

def notify_proposal_sent(proposal):
    _emit(
        proposal, proposal.empresa,
        type=Notification.Type.PROPOSAL_SENT,
        title=f"Proposta enviada: {proposal.number}",
        body=f"A proposta {proposal.number} foi enviada ao cliente.",
        icon="paper-airplane",
        url=_safe_reverse("proposals:detail", proposal.pk),
        payload={"proposal_id": proposal.pk},
        lead=getattr(proposal, "lead", None),
    )


def notify_proposal_accepted(proposal):
    _emit(
        proposal, proposal.empresa,
        type=Notification.Type.PROPOSAL_ACCEPTED,
        title=f"Proposta aceita: {proposal.number}",
        body=f"O cliente aceitou a proposta {proposal.number}.",
        icon="check-circle",
        url=_safe_reverse("proposals:detail", proposal.pk),
        payload={"proposal_id": proposal.pk},
        lead=getattr(proposal, "lead", None),
    )


# --- Contratos ---------------------------------------------------------------

def notify_contract_sent(contract):
    _emit(
        contract, contract.empresa,
        type=Notification.Type.CONTRACT_SENT,
        title="Contrato enviado",
        body=f"O contrato {getattr(contract, 'number', '')} foi enviado ao cliente.".strip(),
        icon="paper-airplane",
        url=_safe_reverse("contracts:detail", contract.pk),
        payload={"contract_id": contract.pk},
        lead=getattr(contract, "lead", None),
    )


def notify_contract_signed(contract):
    _emit(
        contract, contract.empresa,
        type=Notification.Type.CONTRACT_SIGNED,
        title="Contrato assinado",
        body=f"O contrato {getattr(contract, 'number', '')} foi assinado pelo cliente.".strip(),
        icon="pencil-square",
        url=_safe_reverse("contracts:detail", contract.pk),
        payload={"contract_id": contract.pk},
        lead=getattr(contract, "lead", None),
    )


# --- Lead movimentado --------------------------------------------------------

def notify_lead_moved(lead, from_stage, to_stage):
    _emit(
        lead, lead.empresa,
        type=Notification.Type.LEAD_MOVED,
        title=f"Lead movimentado: {lead.name}",
        body=f"'{lead.name}' foi movido para {getattr(to_stage, 'name', '—')}.",
        icon="arrow-trending-up",
        url=_safe_reverse("crm:lead_detail", lead.pk),
        payload={"lead_id": lead.pk, "to_stage": getattr(to_stage, "name", "")},
        lead=lead,
    )


# --- Serviço (OS) ------------------------------------------------------------

def notify_service_started(work_order):
    _emit(
        work_order, work_order.empresa,
        type=Notification.Type.SERVICE_STARTED,
        title=f"Serviço iniciado: {work_order.number}",
        body=f"A OS {work_order.number} entrou em andamento.",
        icon="bolt",
        url=_safe_reverse("operations:work_order_detail", work_order.pk),
        payload={"work_order_id": work_order.pk},
        lead=getattr(work_order, "lead", None),
        extra_user=getattr(work_order, "assigned_to", None),
    )


def notify_service_completed(work_order):
    _emit(
        work_order, work_order.empresa,
        type=Notification.Type.SERVICE_COMPLETED,
        title=f"Serviço concluído: {work_order.number}",
        body=f"A OS {work_order.number} foi concluída.",
        icon="check-circle",
        url=_safe_reverse("operations:work_order_detail", work_order.pk),
        payload={"work_order_id": work_order.pk},
        lead=getattr(work_order, "lead", None),
        extra_user=getattr(work_order, "assigned_to", None),
    )


# --- Follow-up de lead (PART B) ---------------------------------------------

def emit_lead_followup(lead, threshold_days, days_since):
    """Emite a notificação de follow-up e retorna a última Notification criada
    (usada pela task para registrar o marcador de idempotência)."""
    last = None
    url = _safe_reverse("crm:lead_detail", lead.pk)
    for user in _resolve_recipients(lead.empresa, lead):
        notif = notify(
            user,
            type=Notification.Type.LEAD_FOLLOWUP,
            title=f"Lead sem contato há {days_since} dias: {lead.name}",
            body=(
                "Faz tempo que não há contato com este lead. "
                "Retome o contato antes de descartá-lo."
            ),
            url=url, icon="bell", empresa=lead.empresa,
            payload={
                "lead_id": lead.pk,
                "threshold_days": threshold_days,
                "days_since": days_since,
            },
        )
        # RV07 (6.2) — mantém o último notif REAL (notify retorna None se o
        # usuário silenciou o follow-up); a idempotência do reminder já foi
        # registrada pela task antes desta chamada.
        if notif is not None:
            last = notif
    return last
