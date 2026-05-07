"""Brazilian document validators (CPF / CNPJ).

Both validators accept empty strings (optional fields). Non-empty values are
validated using the standard mod11 algorithm. Input may contain formatting
(dots, slash, dash) which is stripped before checking.
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError


def _only_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _cpf_is_valid(digits: str) -> bool:
    if len(digits) != 11 or digits == digits[0] * 11:
        return False

    def check_digit(base: str, factor_start: int) -> int:
        total = sum(int(d) * f for d, f in zip(base, range(factor_start, 1, -1)))
        remainder = (total * 10) % 11
        return 0 if remainder == 10 else remainder

    return (
        check_digit(digits[:9], 10) == int(digits[9])
        and check_digit(digits[:10], 11) == int(digits[10])
    )


def _cnpj_is_valid(digits: str) -> bool:
    if len(digits) != 14 or digits == digits[0] * 14:
        return False

    def check_digit(base: str) -> int:
        factors = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        factors = factors[-len(base):]
        total = sum(int(d) * f for d, f in zip(base, factors))
        remainder = total % 11
        return 0 if remainder < 2 else 11 - remainder

    return (
        check_digit(digits[:12]) == int(digits[12])
        and check_digit(digits[:13]) == int(digits[13])
    )


def validate_cpf(value: str) -> None:
    """Raise ValidationError if value is a non-empty but invalid CPF."""
    if not value:
        return
    digits = _only_digits(value)
    if not _cpf_is_valid(digits):
        raise ValidationError("CPF inválido.", code="invalid_cpf")


def validate_cnpj(value: str) -> None:
    """Raise ValidationError if value is a non-empty but invalid CNPJ."""
    if not value:
        return
    digits = _only_digits(value)
    if not _cnpj_is_valid(digits):
        raise ValidationError("CNPJ inválido.", code="invalid_cnpj")


def validate_cpf_or_cnpj(value: str) -> None:
    """Accept either a valid CPF or CNPJ. Empty string is allowed."""
    if not value:
        return
    digits = _only_digits(value)
    if len(digits) == 11:
        if not _cpf_is_valid(digits):
            raise ValidationError("CPF inválido.", code="invalid_cpf")
    elif len(digits) == 14:
        if not _cnpj_is_valid(digits):
            raise ValidationError("CNPJ inválido.", code="invalid_cnpj")
    else:
        raise ValidationError(
            "Documento inválido: informe um CPF (11 dígitos) ou CNPJ (14 dígitos).",
            code="invalid_document",
        )


def normalize_document(value: str) -> str:
    """Return only the digits of a CPF/CNPJ. Empty input returns empty string."""
    return _only_digits(value)


def mask_document(value: str) -> str:
    """Mask a CPF/CNPJ for safe logging.

    Examples:
        '12345678901' -> '***.456.789-**'
        '12345678000190' -> '**.345.678/0001-**'
        '' or invalid length -> '***'
    """
    digits = _only_digits(value)
    if len(digits) == 11:
        return f"***.{digits[3:6]}.{digits[6:9]}-**"
    if len(digits) == 14:
        return f"**.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-**"
    return "***"
