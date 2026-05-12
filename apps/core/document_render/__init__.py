"""Camada compartilhada para renderização de documentos (RV05 FASE 2).

Centraliza:
- Sanitização de HTML rich-text (`sanitizer.py`)
- Validação de imagens de cabeçalho/rodapé (`image_validation.py`)
- Geração de PDF segura via WeasyPrint (`pdf.py`)

Use os submódulos diretamente:
    from apps.core.document_render.sanitizer import sanitize_rich_html
    from apps.core.document_render.image_validation import validate_document_image
    from apps.core.document_render.pdf import render_html_to_pdf

DOCX **não** é abstraído (decisão arquitetural — idiossincrático por documento).
"""
