"""Envio de contrato por WhatsApp via Evolution API.

Padrão idêntico ao de Proposal: tenta enviar PDF anexado (sendMedia). Se falhar,
faz fallback para link público do contrato com mensagem de texto.

Erros sempre são logados — nunca silenciados (RV06 #6).
"""
from __future__ import annotations

import base64
import logging

from django.utils import timezone

from apps.chatbot.models import WhatsAppConfig
from apps.chatbot.whatsapp import EvolutionAPIClient
from apps.contracts.models import Contract
from apps.contracts.services.render import render_contract_pdf

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


def _build_public_link(contract: Contract, request) -> str:
    if request is not None:
        path = f"/c/{contract.public_token}/"
        return request.build_absolute_uri(path)
    return f"/c/{contract.public_token}/"


def send_contract_whatsapp(
    contract: Contract,
    to_phone: str,
    message: str | None = None,
    request=None,
) -> tuple[bool, str, str]:
    """Envia contrato por WhatsApp.

    Returns:
        (success, mode, message). mode ∈ {"attachment", "link", "failed"}.
    """
    if not to_phone:
        return False, "failed", "Telefone do lead não está cadastrado."

    client, err = _client_for_empresa(contract.empresa)
    if not client:
        return False, "failed", err

    if not getattr(client, "configured", True):
        return False, "failed", (
            "Evolution API não está configurada para esta empresa. "
            "Vá em Configurações → WhatsApp."
        )

    phone = "".join(c for c in to_phone if c.isdigit())
    if not phone:
        return False, "failed", f"Telefone '{to_phone}' não contém dígitos."

    custom_msg = (message or "").strip()
    public_url = _build_public_link(contract, request)
    media_err = ""

    # 1) Tentativa: anexar PDF
    try:
        pdf_bytes = render_contract_pdf(contract, request=request)
        pdf_kb = len(pdf_bytes) // 1024
        b64 = base64.b64encode(pdf_bytes).decode("ascii")
        caption = (
            custom_msg
            or f"Olá! Segue o contrato {contract.number} em anexo."
        )
        logger.info(
            "send_contract_whatsapp attempt=media contract=%s pdf_kb=%s",
            contract.pk, pdf_kb,
        )
        ok, err_msg = client.send_media(
            phone=phone,
            base64_content=b64,
            filename=f"Contrato_{contract.number}.pdf",
            caption=caption,
            mime_type="application/pdf",
        )
        if ok:
            _post_send_success(contract)
            logger.info(
                "send_contract_whatsapp success=media contract=%s", contract.pk,
            )
            return True, "attachment", "Contrato enviado com PDF anexado."
        media_err = err_msg or "erro desconhecido"
        logger.warning(
            "send_contract_whatsapp media_failed contract=%s err=%s",
            contract.pk, media_err,
        )
    except Exception as exc:  # noqa: BLE001
        media_err = f"exceção: {exc!r}"
        logger.exception(
            "send_contract_whatsapp media_exception contract=%s", contract.pk,
        )

    # 2) Fallback: link público
    text = (
        custom_msg
        + ("\n\n" if custom_msg else "")
        + f"Olá! Seu contrato está pronto: {public_url}"
    ).strip()
    logger.info(
        "send_contract_whatsapp attempt=link contract=%s", contract.pk,
    )
    try:
        link_ok = client.send_text(phone, text)
    except Exception:  # noqa: BLE001
        logger.exception(
            "send_contract_whatsapp link_exception contract=%s", contract.pk,
        )
        link_ok = False

    if link_ok:
        _post_send_success(contract)
        return True, "link", (
            "PDF não pôde ser anexado; enviei o link de visualização."
        )

    logger.error(
        "send_contract_whatsapp failed_total contract=%s err=%s",
        contract.pk, media_err,
    )
    # Diagnóstico reusa o helper de proposals para mensagens consistentes
    from apps.proposals.services.whatsapp import _diagnose_failure
    diagnosis = _diagnose_failure(media_err)
    return False, "failed", (
        f"Não foi possível enviar pelo WhatsApp. {diagnosis} "
        f"Copie e envie manualmente: {public_url}"
    )


def _post_send_success(contract: Contract):
    """Atualiza timestamps após envio bem-sucedido."""
    now = timezone.now()
    contract.last_whatsapp_sent_at = now
    update_fields = ["last_whatsapp_sent_at", "updated_at"]
    if contract.status == Contract.Status.DRAFT:
        contract.status = Contract.Status.SENT
        update_fields.append("status")
    if not contract.sent_at:
        contract.sent_at = now
        update_fields.append("sent_at")
    contract.save(update_fields=update_fields)
