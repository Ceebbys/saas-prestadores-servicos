"""Render PDF compartilhado: WeasyPrint + url_fetcher seguro.

`media_url_fetcher` lê arquivos `/media/...` direto do storage Django
(funciona com FileSystemStorage local ou futuro S3) em vez de fazer
roundtrip HTTP. Bloqueia esquemas perigosos (`file://`, `data:`) e
URLs externas, prevenindo SSRF via `<img src="file:///etc/passwd">`.
"""
from __future__ import annotations

import logging
import mimetypes
from urllib.parse import urlparse

from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)


# Esquemas perigosos — não deixar WeasyPrint resolver direto.
_BLOCKED_SCHEMES = {"file", "ftp", "ftps"}

# Hosts sempre considerados "internos" — fetcher resolve via default_storage.
# Outros hosts são "internos" apenas se o caller passar via factory abaixo.
_ALWAYS_INTERNAL_HOSTS = {"", "localhost", "127.0.0.1"}

# Base URL default quando o caller não passa request — WeasyPrint precisa de
# algo para fazer urljoin de URLs relativas /media/img.png. Sem isso, emite
# warning e pula a imagem.
DEFAULT_BASE_URL = "http://localhost/"


def _guess_mime(name: str) -> str:
    mime, _ = mimetypes.guess_type(name)
    return mime or "application/octet-stream"


def _make_media_url_fetcher(internal_hosts: frozenset):
    """Factory: produz um url_fetcher que trata `internal_hosts` como locais.

    Internal hosts incluem sempre localhost/127.0.0.1/vazio, mais o que o
    caller passar (tipicamente o host do request atual).
    """
    allowed = _ALWAYS_INTERNAL_HOSTS | internal_hosts

    def fetcher(url: str) -> dict:
        parsed = urlparse(url)

        if parsed.scheme in _BLOCKED_SCHEMES:
            raise ValueError(f"Esquema bloqueado: {parsed.scheme}")

        # data: URIs — só imagem
        if parsed.scheme == "data":
            if parsed.path.split(",", 1)[0].startswith("image/"):
                from weasyprint.urls import default_url_fetcher
                return default_url_fetcher(url)
            raise ValueError("data: URIs não-imagem bloqueados")

        # Resolve /media/* via storage Django se o host é "interno".
        # Hosts externos (https://attacker.com/media/...) NÃO entram aqui —
        # vão para o fetcher default que faz HTTP real (defesa SSRF).
        if parsed.path.startswith("/media/") and parsed.netloc in allowed:
            name = parsed.path[len("/media/"):]
            try:
                if default_storage.exists(name):
                    f = default_storage.open(name, "rb")
                    return {
                        "file_obj": f,
                        "mime_type": _guess_mime(name),
                    }
            except Exception:
                logger.exception("Falha ao ler %s via default_storage", name)
                # cai no fetcher default abaixo

        from weasyprint.urls import default_url_fetcher
        return default_url_fetcher(url)

    return fetcher


def media_url_fetcher(url: str) -> dict:
    """Fetcher padrão (somente localhost/127.0.0.1 como interno).

    Use `_make_media_url_fetcher(...)` para incluir o host do request atual.
    Mantido para retrocompatibilidade e testes.
    """
    parsed = urlparse(url)

    if parsed.scheme in _BLOCKED_SCHEMES:
        raise ValueError(f"Esquema bloqueado: {parsed.scheme}")

    if parsed.path.startswith("/media/") and parsed.netloc in _ALWAYS_INTERNAL_HOSTS:
        name = parsed.path[len("/media/"):]
        try:
            if default_storage.exists(name):
                f = default_storage.open(name, "rb")
                return {
                    "file_obj": f,
                    "mime_type": _guess_mime(name),
                }
        except Exception:
            logger.exception("Falha ao ler %s via default_storage", name)
    # data: URIs com binary OK; data:text/html com script é bloqueado por sanitizer
    if parsed.scheme == "data":
        # Permite data: (Quill às vezes gera) mas só se for imagem
        if parsed.path.split(",", 1)[0].startswith("image/"):
            from weasyprint.urls import default_url_fetcher
            return default_url_fetcher(url)
        raise ValueError("data: URIs não-imagem bloqueados")

    # http/https externos: deixa WeasyPrint resolver (com timeout default)
    from weasyprint.urls import default_url_fetcher
    return default_url_fetcher(url)


def render_html_to_pdf(html: str, *, base_url: str | None = None) -> bytes:
    """Render HTML to PDF bytes usando WeasyPrint + url_fetcher seguro.

    Args:
        html: HTML string completa.
        base_url: para resolver URLs relativas. Tipicamente vem de
                  `request.build_absolute_uri('/')`. Se None, usa
                  `DEFAULT_BASE_URL` ("http://localhost/").

    O fetcher criado considera o host do `base_url` como interno (resolve
    `/media/*` via storage). Outros hosts continuam externos (HTTP real).

    Returns:
        bytes do PDF.

    Raises:
        ValueError: schemes bloqueados, recursos inválidos.
        Exception: falha do WeasyPrint (libs nativas, parse, etc.).
    """
    import weasyprint

    effective_base = base_url or DEFAULT_BASE_URL
    base_host = urlparse(effective_base).netloc
    fetcher = _make_media_url_fetcher(frozenset({base_host}) if base_host else frozenset())

    return weasyprint.HTML(
        string=html,
        base_url=effective_base,
        url_fetcher=fetcher,
    ).write_pdf()
