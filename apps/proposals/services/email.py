"""Envio de proposta por e-mail.

Reutiliza o backend SMTP global do projeto (configurado para password reset).
SMTP por tenant é melhoria futura — documentado no plano.

Returns sempre `(success: bool, error_message: str)` — view consome e exibe ao usuário.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from apps.proposals.models import Proposal
from apps.proposals.services.render import render_proposal_pdf

logger = logging.getLogger(__name__)


def send_proposal_email(
    proposal: Proposal,
    to_email: str,
    subject: str | None = None,
    message: str | None = None,
    request=None,
) -> tuple[bool, str]:
    """Envia proposta por e-mail com PDF anexado.

    Args:
        proposal: instância de Proposal já em scope da empresa.
        to_email: destinatário (validado no caller).
        subject/message: opcionais, sobrescrevem defaults.

    Returns:
        (success, error_message). Em sucesso: marca `last_email_sent_at` e
        transiciona para SENT (se ainda em DRAFT).
    """
    if not to_email:
        return False, "Endereço de e-mail não fornecido."

    empresa_name = proposal.empresa.name or "Equipe"
    subject = subject or f"Proposta {proposal.number} — {empresa_name}"
    message = (message or "").strip()

    # Gera PDF in-memory
    try:
        pdf_bytes = render_proposal_pdf(proposal, request=request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao gerar PDF para envio por e-mail")
        return False, f"Não foi possível gerar PDF: {exc}"

    # Templates HTML + texto
    ctx = {
        "proposal": proposal,
        "empresa": proposal.empresa,
        "custom_message": message,
    }
    try:
        html_body = render_to_string("emails/proposal_send.html", ctx)
        text_body = render_to_string("emails/proposal_send.txt", ctx)
    except Exception:
        # Templates ausentes — fallback simples
        text_body = (
            (message or "")
            + f"\n\nSegue em anexo a proposta {proposal.number}."
        )
        html_body = None

    from_email = (
        getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "EMAIL_HOST_USER", "")
        or "no-reply@servicopro.app"
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=[to_email],
    )
    if html_body:
        msg.attach_alternative(html_body, "text/html")
    msg.attach(
        f"Proposta_{proposal.number}.pdf",
        pdf_bytes,
        "application/pdf",
    )

    try:
        msg.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao enviar e-mail de proposta")
        return False, f"Falha ao enviar: {exc}"

    # Sucesso: registra timestamp e transita status se ainda em rascunho
    now = timezone.now()
    proposal.last_email_sent_at = now
    update_fields = ["last_email_sent_at", "updated_at"]
    if proposal.status == Proposal.Status.DRAFT:
        proposal.status = Proposal.Status.SENT
        proposal.sent_at = now
        update_fields.extend(["status", "sent_at"])
    proposal.save(update_fields=update_fields)

    return True, ""
