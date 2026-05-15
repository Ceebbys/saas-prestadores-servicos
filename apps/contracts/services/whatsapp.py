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
        return False, "failed", "Telefone não fornecido."

    client, err = _client_for_empresa(contract.empresa)
    if not client:
        return False, "failed", err

    phone = "".join(c for c in to_phone if c.isdigit())
    custom_msg = (message or "").strip()

    # 1) Tentativa: anexar PDF
    try:
        pdf_bytes = render_contract_pdf(contract, request=request)
        b64 = base64.b64encode(pdf_bytes).decode("ascii")
        caption = (
            custom_msg
            or f"Olá! Segue o contrato {contract.number} em anexo."
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
            return True, "attachment", "Contrato enviado com PDF anexado."
        logger.info(
            "send_contract_whatsapp: send_media falhou (%s) — tentando fallback link",
            err_msg,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Falha gerando/enviando PDF anexo de contrato via WhatsApp")

    # 2) Fallback: link público
    public_url = _build_public_link(contract, request)
    text = (
        custom_msg
        + ("\n\n" if custom_msg else "")
        + f"Olá! Seu contrato está pronto: {public_url}"
    ).strip()
    if client.send_text(phone, text):
        _post_send_success(contract)
        return True, "link", (
            "Anexo PDF falhou — link de visualização enviado com sucesso."
        )

    return False, "failed", (
        "Não foi possível enviar via WhatsApp. "
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
