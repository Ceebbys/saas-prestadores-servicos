"""Compatibilidade RV03 — use apps.core.document_render.sanitizer.

Mantém o nome `sanitize_proposal_html` como alias para `sanitize_rich_html`
(o sanitizer agora é compartilhado com contratos e outros documentos).
"""
from apps.core.document_render.sanitizer import (  # noqa: F401
    ALLOWED_ATTRIBUTES,
    ALLOWED_TAGS,
    SAFE_STYLE_PROPS,
    SANITIZER_VERSION,
    sanitize_rich_html as sanitize_proposal_html,
)
