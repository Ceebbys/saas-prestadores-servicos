"""V2A — Gerenciamento de segredos do chatbot (Fernet).

`ChatbotSecret.value_encrypted` é BinaryField. Wrapper aqui converte
para/de string para alinhar com `apps.core.encryption` (que usa str b64).

Uso:
    from apps.chatbot.builder.services.secrets import set_secret_value, get_secret_value
    secret = ChatbotSecret.objects.create(empresa=..., name="crm_api_key")
    set_secret_value(secret, "abc-123-xyz")
    secret.save()

    # Depois:
    plain = get_secret_value(secret)  # → "abc-123-xyz" ou "" se falha
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils import timezone

from apps.core.encryption import decrypt, encrypt

if TYPE_CHECKING:
    from apps.chatbot.models import ChatbotSecret


def set_secret_value(secret: "ChatbotSecret", plaintext: str) -> None:
    """Encripta + grava em `value_encrypted` (não chama save automático)."""
    ciphertext_str = encrypt(plaintext or "")
    # BinaryField aceita bytes
    secret.value_encrypted = ciphertext_str.encode("ascii") if ciphertext_str else b""


def get_secret_value(secret: "ChatbotSecret") -> str:
    """Descriptografa. Atualiza `last_used_at`. Retorna '' se falha."""
    raw = secret.value_encrypted
    if not raw:
        return ""
    text = raw.decode("ascii") if isinstance(raw, (bytes, memoryview)) else raw
    plain = decrypt(text)
    # Toca last_used_at de forma assíncrona ao plain (não bloqueia execução).
    type(secret).objects.filter(pk=secret.pk).update(last_used_at=timezone.now())
    return plain


def has_secret_value(secret: "ChatbotSecret") -> bool:
    """True se há valor criptografado (sem decriptar)."""
    return bool(secret.value_encrypted)
