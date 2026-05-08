"""Envio de proposta por WhatsApp via Evolution API.

Estratégia: tenta enviar PDF anexado (sendMedia). Se falhar (versão da Evolution,
limites de payload, MIME quirks, instância offline), faz fallback para link
público da proposta com mensagem de texto.

Erros sempre são surfaceados — nunca silenciados.
"""
from __future__ import annotations

import base64
import logging

from django.utils import timezone

from apps.chatbot.models import WhatsAppConfig
from apps.chatbot.whatsapp import EvolutionAPIClient
from apps.proposals.models import Proposal
from apps.proposals.services.render import render_proposal_pdf

logger = logging.getLogger(__name__)


def _client_for_empresa(empresa):
    """Resolve o EvolutionAPIClient da empresa via WhatsAppConfig."""
    cfg = WhatsAppConfig.objects.filter(empresa=empresa).first()
    if not cfg:
        return None, "Empresa não tem WhatsApp configurado (vá em Configurações)."
    return (
        EvolutionAPIClient(
            api_url=cfg.effective_api_url,
            api_key=cfg.effective_instance_key,
            instance=cfg.instance_name,
        ),
        "",
    )


def _build_public_link(proposal: Proposal, request) -> str:
    if request is not None:
        path = f"/p/{proposal.public_token}/"
        return request.build_absolute_uri(path)
    # Fallback sem request — link relativo (caller deve completar)
    return f"/p/{proposal.public_token}/"


def send_proposal_whatsapp(
    proposal: Proposal,
    to_phone: str,
    message: str | None = None,
    request=None,
) -> tuple[bool, str, str]:
    """Envia proposta por WhatsApp.

    Returns:
        (success, mode, message). mode ∈ {"attachment", "link", "failed"}.
        message é a mensagem de status amigável para exibir ao usuário.
    """
    if not to_phone:
        return False, "failed", "Telefone não fornecido."

    client, err = _client_for_empresa(proposal.empresa)
    if not client:
        return False, "failed", err

    # Limpeza simples do telefone (Evolution costuma aceitar 5511…)
    phone = "".join(c for c in to_phone if c.isdigit())

    custom_msg = (message or "").strip()

    # 1) Tentativa: anexar PDF
    try:
        pdf_bytes = render_proposal_pdf(proposal, request=request)
        b64 = base64.b64encode(pdf_bytes).decode("ascii")
        caption = (
            custom_msg
            or f"Olá! Segue a proposta {proposal.number} em anexo."
        )
        ok, err_msg = client.send_media(
            phone=phone,
            base64_content=b64,
            filename=f"Proposta_{proposal.number}.pdf",
            caption=caption,
            mime_type="application/pdf",
        )
        if ok:
            _post_send_success(proposal)
            return True, "attachment", "Proposta enviada com PDF anexado."
        logger.info(
            "send_media falhou (%s) — tentando fallback para link", err_msg,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha gerando/enviando PDF anexo via WhatsApp")
        # cai no fallback de link

    # 2) Fallback: link público
    public_url = _build_public_link(proposal, request)
    text = (
        custom_msg
        + ("\n\n" if custom_msg else "")
        + f"Olá! Sua proposta está pronta: {public_url}"
    ).strip()
    if client.send_text(phone, text):
        _post_send_success(proposal)
        return True, "link", (
            "Anexo PDF falhou — link de visualização enviado com sucesso."
        )

    return False, "failed", (
        "Não foi possível enviar via WhatsApp. "
        f"Copie e envie manualmente: {public_url}"
    )


def _post_send_success(proposal: Proposal):
    """Atualiza timestamps e transita status DRAFT→SENT após envio bem-sucedido."""
    now = timezone.now()
    proposal.last_whatsapp_sent_at = now
    update_fields = ["last_whatsapp_sent_at", "updated_at"]
    if proposal.status == Proposal.Status.DRAFT:
        proposal.status = Proposal.Status.SENT
        proposal.sent_at = now
        update_fields.extend(["status", "sent_at"])
    proposal.save(update_fields=update_fields)
