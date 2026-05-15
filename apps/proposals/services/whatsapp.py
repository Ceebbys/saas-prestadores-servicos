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

    RV06 #6 — Logs estruturados + mensagens de erro úteis (cada tentativa
    deixa rastro claro em journalctl + retorna mensagem específica para o admin).

    Returns:
        (success, mode, message). mode ∈ {"attachment", "link", "failed"}.
        message é amigável e diz **o que** falhou e **como agir**.
    """
    if not to_phone:
        return False, "failed", "Telefone do lead não está cadastrado. Edite o lead e adicione o número antes de enviar."

    client, err = _client_for_empresa(proposal.empresa)
    if not client:
        return False, "failed", err

    # Verifica explicitamente que client tem credenciais
    if not getattr(client, "configured", True):
        logger.warning(
            "send_proposal_whatsapp: Evolution não configurada (proposal=%s empresa=%s)",
            proposal.pk, proposal.empresa_id,
        )
        return False, "failed", (
            "Evolution API não está configurada para esta empresa. "
            "Vá em Configurações → WhatsApp e preencha URL/Token/Instância."
        )

    # Limpeza simples do telefone (Evolution costuma aceitar 5511…)
    phone = "".join(c for c in to_phone if c.isdigit())
    if not phone:
        return False, "failed", (
            f"Telefone '{to_phone}' não contém dígitos válidos. "
            "Verifique o cadastro do lead."
        )

    custom_msg = (message or "").strip()
    public_url = _build_public_link(proposal, request)

    # 1) Tentativa: anexar PDF
    pdf_size_kb = None
    media_err: str = ""
    try:
        pdf_bytes = render_proposal_pdf(proposal, request=request)
        pdf_size_kb = len(pdf_bytes) // 1024
        b64 = base64.b64encode(pdf_bytes).decode("ascii")
        caption = (
            custom_msg
            or f"Olá! Segue a proposta {proposal.number} em anexo."
        )
        logger.info(
            "send_proposal_whatsapp attempt=media proposal=%s empresa=%s phone=%s pdf_kb=%s",
            proposal.pk, proposal.empresa_id, phone, pdf_size_kb,
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
            logger.info(
                "send_proposal_whatsapp success=media proposal=%s pdf_kb=%s",
                proposal.pk, pdf_size_kb,
            )
            return True, "attachment", "Proposta enviada com PDF anexado."
        media_err = err_msg or "erro desconhecido"
        logger.warning(
            "send_proposal_whatsapp media_failed proposal=%s empresa=%s pdf_kb=%s err=%s — tentando link",
            proposal.pk, proposal.empresa_id, pdf_size_kb, media_err,
        )
    except Exception as exc:  # noqa: BLE001
        media_err = f"exceção: {exc!r}"
        logger.exception(
            "send_proposal_whatsapp media_exception proposal=%s",
            proposal.pk,
        )
        # cai no fallback de link

    # 2) Fallback: link público
    text = (
        custom_msg
        + ("\n\n" if custom_msg else "")
        + f"Olá! Sua proposta está pronta: {public_url}"
    ).strip()
    logger.info(
        "send_proposal_whatsapp attempt=link proposal=%s phone=%s",
        proposal.pk, phone,
    )
    try:
        link_ok = client.send_text(phone, text)
    except Exception:  # noqa: BLE001
        logger.exception(
            "send_proposal_whatsapp link_exception proposal=%s", proposal.pk,
        )
        link_ok = False

    if link_ok:
        _post_send_success(proposal)
        logger.info(
            "send_proposal_whatsapp success=link proposal=%s (media falhou antes)",
            proposal.pk,
        )
        return True, "link", (
            "PDF não pôde ser anexado (instância WhatsApp pode estar offline ou "
            "limite de tamanho atingido); enviei o link de visualização."
        )

    # Ambos falharam — retorna diagnóstico para o admin
    logger.error(
        "send_proposal_whatsapp failed_total proposal=%s empresa=%s media_err=%s",
        proposal.pk, proposal.empresa_id, media_err,
    )
    diagnosis = _diagnose_failure(media_err)
    return False, "failed", (
        f"Não foi possível enviar pelo WhatsApp. "
        f"{diagnosis} "
        f"Copie e envie manualmente: {public_url}"
    )


def _diagnose_failure(media_err: str) -> str:
    """Mensagem de diagnóstico humana baseada no erro da Evolution API."""
    import re
    e = (media_err or "").lower()
    if "401" in e or "unauthor" in e:
        return "Token/credenciais inválidos — verifique a API Key da Evolution."
    if "404" in e or "not found" in e or "does not exist" in e:
        return "Instância WhatsApp não encontrada na Evolution — verifique o nome da instância em Configurações."
    if "connecting" in e or "close" in e or "offline" in e:
        return "WhatsApp Web não está conectado — abra o painel da Evolution e parea o QR code novamente."
    if "timeout" in e:
        return "Tempo esgotado conectando à Evolution API — pode haver instabilidade de rede."
    # HTTP 5xx — qualquer 5\d\d na mensagem
    if re.search(r"\b5\d\d\b", e):
        return "Erro no servidor da Evolution API (5xx) — tente novamente em alguns minutos."
    return "Verifique se a instância WhatsApp está conectada (state=open na Evolution)."


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
