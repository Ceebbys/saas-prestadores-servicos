"""Celery tasks do app crm — follow-up automático de leads (RV07 6.2)."""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="apps.crm.tasks.evaluate_lead_followups")
def evaluate_lead_followups() -> dict:
    """RV07 (6.2) — Gera lembretes de follow-up para leads sem contato.

    Beat-scheduled (1x/dia). Idempotente: lock per-tenant (Redis cache) +
    marcador ``LeadFollowUpReminder`` por (lead, threshold, base de último
    contato). Política: dispara apenas o MAIOR limiar cruzado por ciclo e
    registra os menores como satisfeitos (evita 4 notificações empilhadas em
    um lead muito antigo). Um novo LeadContact reinicia o ciclo.
    """
    from django.core.cache import cache
    from django.db.models import Max
    from django.utils import timezone

    from apps.accounts.models import Empresa
    from apps.communications.notifications_events import emit_lead_followup
    from apps.crm.models import (
        Lead,
        LeadContact,
        LeadFollowUpReminder,
        get_effective_followup_settings,
    )

    summary = {"empresas": 0, "leads_checked": 0, "reminders": 0, "errors": []}
    now = timezone.now()

    for empresa in Empresa.objects.filter(is_active=True):
        lock_key = f"followup-eval-empresa-{empresa.pk}"
        if not cache.add(lock_key, "1", timeout=600):
            continue
        try:
            cfg = get_effective_followup_settings(empresa, user=None)
            if not cfg.enabled:
                continue
            thresholds = cfg.thresholds()
            if not thresholds:
                continue

            leads = (
                Lead.objects.filter(empresa=empresa)
                .exclude(pipeline_stage__is_won=True)
                .exclude(pipeline_stage__is_lost=True)
                .select_related("pipeline_stage", "assigned_to")
            )
            last_contacts = dict(
                LeadContact.objects.filter(empresa=empresa, lead__in=leads)
                .values("lead_id")
                .annotate(m=Max("contacted_at"))
                .values_list("lead_id", "m")
            )
            for lead in leads.iterator(chunk_size=500):
                summary["leads_checked"] += 1
                last = last_contacts.get(lead.pk) or lead.created_at
                if last is None:
                    continue
                days = (now - last).days
                crossed = [t for t in thresholds if days >= t]
                if not crossed:
                    continue
                top = crossed[-1]
                obj, created = LeadFollowUpReminder.objects.get_or_create(
                    empresa=empresa, lead=lead, threshold_days=top,
                    last_contact_at=last, defaults={"notified_at": now},
                )
                if not created:
                    continue  # já notificado neste ciclo
                # Limiares inferiores: registra como satisfeitos (sem notificar)
                for lower in crossed[:-1]:
                    LeadFollowUpReminder.objects.get_or_create(
                        empresa=empresa, lead=lead, threshold_days=lower,
                        last_contact_at=last, defaults={"notified_at": now},
                    )
                notif = emit_lead_followup(lead, top, days)
                if notif is not None:
                    obj.notification = notif
                    obj.save(update_fields=["notification"])
                # EPIC 7 — cria um evento na agenda conectada (Google) p/ o
                # follow-up. Best-effort: no-op seguro se não houver integração,
                # e uma falha aqui jamais derruba a avaliação de follow-ups.
                try:
                    from apps.integrations.services import (
                        create_calendar_event_for_followup,
                    )
                    create_calendar_event_for_followup(
                        lead, when=now, title=f"Follow-up: {lead.name}",
                        description=(
                            f"Lead sem contato há {days} dias. "
                            "Retome antes de descartá-lo."
                        ),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "followup calendar hook failed lead=%s", lead.pk,
                    )
                summary["reminders"] += 1
            summary["empresas"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("followup_eval_failed empresa=%s", empresa.pk)
            summary["errors"].append(f"empresa={empresa.pk}: {exc!r}"[:300])
        finally:
            cache.delete(lock_key)

    logger.info("crm.evaluate_lead_followups %s", summary)
    return summary
