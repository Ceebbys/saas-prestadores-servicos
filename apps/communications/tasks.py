"""Celery tasks do app communications.

Tarefas finas — regra de negócio em services.py / services_imap.py /
notifications.py.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="apps.communications.tasks.poll_email_inboxes")
def poll_email_inboxes() -> dict:
    """Polling IMAP per-tenant.

    Beat-scheduled (default: a cada 5 min em `config/celery.py`).

    Idempotente: usa lock per-tenant via Django cache (Redis) + dedupe
    por Message-ID na DB. Falha de um tenant não impacta outros.
    """
    from apps.communications.services_imap import poll_all_inboxes

    summary = poll_all_inboxes()
    logger.info(
        "communications.poll_email_inboxes polled=%s errors=%s",
        summary.get("polled"),
        len(summary.get("errors") or []),
    )
    return summary


@shared_task(name="apps.communications.tasks.send_daily_digest")
def send_daily_digest() -> dict:
    """Envia digest diário por e-mail para usuários com notificações não lidas.

    Beat-scheduled — recomendado 1x/dia às 8h:
        crontab(hour=8, minute=0)

    Para cada usuário com notificações não lidas das últimas 24h, envia
    um e-mail resumo com listagem (até 20). Notificações continuam não
    lidas após o envio — só ficam lidas quando o usuário clica.

    Tolerante a falha SMTP — falha de um user não impacta os outros.
    """
    from datetime import timedelta

    from django.conf import settings as django_settings
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    from django.utils import timezone

    from apps.communications.models import Notification

    cutoff = timezone.now() - timedelta(hours=24)
    site_url = getattr(django_settings, "SITE_URL", "https://servicopro.app").rstrip("/")
    summary = {"users": 0, "emails": 0, "errors": []}

    # Agrupa por user usando aggregate de notificações não lidas recentes
    user_ids = (
        Notification.objects
        .filter(read_at__isnull=True, created_at__gte=cutoff)
        .values_list("user_id", flat=True)
        .distinct()
    )

    from apps.accounts.models import User
    users = User.objects.filter(pk__in=list(user_ids), is_active=True).exclude(email="")
    for user in users:
        try:
            notifs = list(
                Notification.objects
                .filter(user=user, read_at__isnull=True, created_at__gte=cutoff)
                .order_by("-created_at")[:20]
            )
            if not notifs:
                continue
            subject = f"Você tem {len(notifs)} notificação(ões) não lida(s) no ServiçoPro"
            # Pré-resolve URLs absolutas para cada notificação (templates Django
            # não permitem atributos com underscore — usamos lista de dicts).
            items = [
                {
                    "notif": n,
                    "url": (
                        f"{site_url}{n.url}" if n.url and n.url.startswith("/")
                        else (n.url or site_url)
                    ),
                }
                for n in notifs
            ]
            text_body = render_to_string(
                "communications/emails/daily_digest.txt",
                {
                    "user": user,
                    "items": items,
                    "notifications": notifs,  # mantém compat
                    "count": len(notifs),
                    "site_url": site_url,
                },
            )
            send_mail(
                subject=subject,
                message=text_body,
                from_email=None,  # usa DEFAULT_FROM_EMAIL
                recipient_list=[user.email],
                fail_silently=False,
            )
            summary["emails"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "digest_send_failed user_id=%s",
                user.pk,
            )
            summary["errors"].append(f"user={user.pk}: {exc!r}"[:300])
        summary["users"] += 1

    logger.info(
        "communications.send_daily_digest users=%s emails=%s errors=%s",
        summary["users"], summary["emails"], len(summary["errors"]),
    )
    return summary
