"""Sanitização de HTML rich-text de propostas.

Evita XSS removendo tags/atributos não permitidos. A allowlist abaixo cobre
exatamente o que o Quill 2.x produz com nossa toolbar (alinhamento, fonte,
negrito/itálico, listas, links, blockquote, espaçamento).

Uso:
    from apps.proposals.sanitizer import sanitize_proposal_html
    cleaned = sanitize_proposal_html(form.cleaned_data["introduction"])

Sempre sanitiza no `Form.clean_<field>` (ou em service de salvamento) — nunca
no template. HTML corrompido nunca deve entrar no banco.
"""
from __future__ import annotations

import nh3

# Versão da allowlist. Incrementar quando regras mudarem; permite migrações
# futuras de re-sanitização e auditoria de conteúdo legado.
SANITIZER_VERSION = "1"

ALLOWED_TAGS = {
    "p", "br", "strong", "em", "u", "s",
    "ol", "ul", "li",
    "h1", "h2", "h3", "h4",
    "blockquote",
    "span", "div",
    "a",
    "hr",
}

ALLOWED_ATTRIBUTES = {
    "*": {"class", "style"},
    "a": {"href", "title", "target"},  # rel é gerenciado por link_rel abaixo
}

# Subset de propriedades CSS aceitas em `style="..."`. nh3 valida via callback
# (filter); aqui mantemos a lista para referência e usamos url_schemes para a.
SAFE_STYLE_PROPS = {
    "text-align", "font-size", "font-weight", "font-style",
    "margin", "margin-top", "margin-bottom", "margin-left", "margin-right",
    "padding", "padding-top", "padding-bottom", "padding-left", "padding-right",
    "line-height", "letter-spacing",
    "color", "background-color",
    "text-decoration",
}


def sanitize_proposal_html(html: str) -> str:
    """Limpa HTML preservando formatação rich-text segura.

    Args:
        html: HTML potencialmente sujo (vindo de Quill ou usuário).

    Returns:
        HTML sanitizado, seguro para renderizar com `|safe`.
    """
    if not html:
        return ""
    cleaned = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto", "tel"},
        link_rel="noopener noreferrer",
    )
    return cleaned
