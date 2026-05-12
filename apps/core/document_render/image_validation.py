"""Validação compartilhada de uploads de imagem de documento.

Aceita PNG/JPG/JPEG/WEBP até 2MB. Pode ser estendido futuramente para
checar dimensões via Pillow se necessário.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError

MAX_DOCUMENT_IMAGE_BYTES = 2 * 1024 * 1024  # 2MB
ALLOWED_DOCUMENT_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def validate_document_image(image):
    """Valida upload: extensão e tamanho. Levanta ValidationError se inválido.

    Args:
        image: UploadedFile (ou None se campo opcional)

    Returns:
        O mesmo image (passa direto se válido ou None)
    """
    if not image:
        return image
    name = (getattr(image, "name", "") or "").lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in ALLOWED_DOCUMENT_IMAGE_EXTS:
        raise ValidationError(
            "Formato não suportado. Use PNG, JPG, JPEG ou WEBP."
        )
    size = getattr(image, "size", 0) or 0
    if size > MAX_DOCUMENT_IMAGE_BYTES:
        raise ValidationError("Imagem muito grande (máximo 2MB).")
    return image
