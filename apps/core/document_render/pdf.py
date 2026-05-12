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

# Hosts considerados "internos" — fetcher resolve via default_storage.
_INTERNAL_HOSTS = {"", "localhost", "127.0.0.1"}

# Base URL default — WeasyPrint precisa de algo para fazer urljoin de URLs
# relativas como /media/img.png. Sem isso, emite warning e pula a imagem.
DEFAULT_BASE_URL = "http://localhost/"


def _guess_mime(name: str) -> str:
    mime, _ = mimetypes.guess_type(name)
    return mime or "application/octet-stream"


def media_url_fetcher(url: str) -> dict:
    """Resolve URLs `/media/*` lendo do storage Django.

    Para outras URLs (https://, http://), delega ao fetcher default do
    WeasyPrint. Bloqueia `file://`, `ftp://`, etc.

    Returns:
        dict no formato esperado pelo `url_fetcher` do WeasyPrint:
        {"file_obj": file, "mime_type": "image/png"} ou {"url": ...}
    """
    parsed = urlparse(url)

    if parsed.scheme in _BLOCKED_SCHEMES:
        raise ValueError(f"Esquema bloqueado: {parsed.scheme}")

    # Resolve URLs /media/* via storage Django:
    # - Sem netloc (URL relativa);
    # - OU netloc interno (localhost/127.0.0.1, comum após urljoin
    #   com DEFAULT_BASE_URL ou request.build_absolute_uri).
    # Externos (https://attacker.com/media/...) NÃO resolvem aqui — vão
    # para o fetcher default do WeasyPrint, que faz requisição HTTP real.
    if parsed.path.startswith("/media/") and parsed.netloc in _INTERNAL_HOSTS:
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
            # cai no fetcher default abaixo, que vai falhar com mensagem clara
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
    """Render HTML to PDF bytes usando WeasyPrint + media_url_fetcher.

    Args:
        html: HTML string completa
        base_url: usado para resolver URLs relativas. Se None, usa
                  `DEFAULT_BASE_URL` ("http://localhost/") — necessário para o
                  WeasyPrint chamar o url_fetcher com URLs absolutas geradas
                  via urljoin. Sem isso, `<img src="/media/...">` em HTML
                  vira warning "Relative URI reference without a base URI" e
                  a imagem é pulada.

    Returns:
        bytes do PDF.

    Raises:
        ValueError: schemes bloqueados, recursos inválidos
        Exception: falha do WeasyPrint (libs nativas, parse, etc.)
    """
    import weasyprint

    return weasyprint.HTML(
        string=html,
        base_url=base_url or DEFAULT_BASE_URL,
        url_fetcher=media_url_fetcher,
    ).write_pdf()
