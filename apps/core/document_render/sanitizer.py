"""Sanitização de HTML rich-text compartilhada (propostas, contratos, etc.).

Evita XSS removendo tags/atributos não permitidos. A allowlist abaixo cobre
exatamente o que o Quill 2.x produz com nossa toolbar (alinhamento, fonte,
negrito/itálico, listas, links, blockquote, espaçamento, font-family).

Diferenças vs. RV03 sanitizer:
- Adiciona `font-family` em SAFE_STYLE_PROPS (Quill FontStyle gera isso)
- Usa `filter_style_properties` do nh3 0.3+ para filtrar CSS props
  individualmente (antes preservava style cru — vulnerável a
  `style="background:url(javascript:...)"`)
- `SANITIZER_VERSION` incrementado para 2 (auditoria de conteúdo legado)

Uso:
    from apps.core.document_render.sanitizer import sanitize_rich_html
    cleaned = sanitize_rich_html(form.cleaned_data["introduction"])

Sempre sanitiza no `Form.clean_<field>` (ou em service de salvamento) — nunca
no template. HTML corrompido nunca deve entrar no banco.
"""
from __future__ import annotations

import nh3

# Versão da allowlist. Incrementar quando regras mudarem; permite migrações
# futuras de re-sanitização e auditoria de conteúdo legado.
SANITIZER_VERSION = "2"

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

# Propriedades CSS aceitas em `style="..."`. nh3 0.3+ filtra automaticamente
# via `filter_style_properties`. Outras propriedades (incluindo background-image,
# url() perigosos, expressões CSS) são removidas pelo sanitizer.
SAFE_STYLE_PROPS = {
    "text-align", "font-size", "font-weight", "font-style", "font-family",
    "margin", "margin-top", "margin-bottom", "margin-left", "margin-right",
    "padding", "padding-top", "padding-bottom", "padding-left", "padding-right",
    "line-height", "letter-spacing",
    "color", "background-color",
    "text-decoration",
    "list-style-type",
}


def sanitize_rich_html(html: str) -> str:
    """Limpa HTML preservando formatação rich-text segura.

    Args:
        html: HTML potencialmente sujo (vindo de Quill ou usuário).

    Returns:
        HTML sanitizado, seguro para renderizar com `|safe`.
    """
    if not html:
        return ""
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto", "tel"},
        link_rel="noopener noreferrer",
        filter_style_properties=SAFE_STYLE_PROPS,
    )
