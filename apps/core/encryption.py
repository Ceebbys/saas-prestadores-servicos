"""Criptografia simétrica para campos sensíveis (senhas SMTP, tokens, etc.).

Usa Fernet (AES-128 CBC + HMAC). Chave vem de `settings.FERNET_KEY` (env var)
e DEVE ser persistente — perder a chave torna os ciphertexts irrecuperáveis.

Geração da chave (uma vez, em deploy):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    → coloca em FERNET_KEY no .env

Em desenvolvimento, se a env var não existir, derivamos uma chave determinística
do SECRET_KEY (NÃO use em produção — DEBUG-only).
"""
from __future__ import annotations

import base64
import hashlib
import os
import sys

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _is_test_run() -> bool:
    """True quando rodando o test runner do Django ou pytest."""
    return "test" in sys.argv or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _resolve_key() -> bytes:
    raw = getattr(settings, "FERNET_KEY", "") or ""
    if raw:
        return raw.encode() if isinstance(raw, str) else raw

    # Modo DEBUG ou suite de testes: deriva chave determinística do SECRET_KEY.
    # Django força DEBUG=False sob test runner, mas ainda precisamos de uma
    # chave funcional para os testes de encrypt/decrypt (FERNET_KEY produção
    # não pode estar disponível em CI).
    if getattr(settings, "DEBUG", False) or _is_test_run():
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

    raise RuntimeError(
        "FERNET_KEY não configurada — defina a variável de ambiente FERNET_KEY "
        "antes de criptografar/descriptografar dados sensíveis em produção."
    )


def _fernet() -> Fernet:
    return Fernet(_resolve_key())


def encrypt(plaintext: str) -> str:
    """Retorna ciphertext em utf-8 string. Aceita strings vazias."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """Retorna plaintext. Em caso de chave inválida, retorna string vazia (não derruba)."""
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""
