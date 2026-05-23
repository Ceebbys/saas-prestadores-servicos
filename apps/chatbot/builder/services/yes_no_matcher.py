"""Detector tolerante de respostas SIM/NÃO em pt-BR.

Aceita variações comuns: 'sim', 's', 'yes', 'ok', 'claro', 'com certeza',
'positivo', 'isso', 'exato', 'certo', 'afirmativo', 'beleza', 'blz' /
'não', 'nao', 'n', 'no', 'nunca', 'jamais', 'negativo', 'nope'.

Tolerante a maiúsculas, acentos, espaços, pontuação e emoji keycap inicial.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


# Sets ordenados por especificidade — frase completa antes de palavra solta
_YES_PHRASES = (
    "com toda certeza",
    "com certeza",
    "sem duvida",
    "claro que sim",
    "positivo",
    "afirmativo",
    "isso mesmo",
    "exato",
    "exatamente",
    "correto",
    "certo",
    "claro",
    "obvio",
    "beleza",
    "fechado",
)
_YES_WORDS = ("sim", "s", "yes", "ok", "okay", "blz", "yep", "yeah", "uhum")

_NO_PHRASES = (
    "de jeito nenhum",
    "nem pensar",
    "claro que nao",
    "absolutamente nao",
    "obvio que nao",
    "negativo",
    "jamais",
    "nunca",
)
_NO_WORDS = ("nao", "n", "no", "nope", "nem", "nada")


@dataclass
class YesNoResult:
    value: str  # "yes", "no" ou "unknown"
    matched_by: str  # "phrase", "word" ou "none"


def detect_yes_no(text: str) -> YesNoResult:
    """Detecta SIM, NÃO ou nenhum dos dois na resposta."""
    if not text:
        return YesNoResult("unknown", "none")
    norm = _normalize(text)
    if not norm:
        return YesNoResult("unknown", "none")

    # 1) Frases (mais específicas)
    for phrase in _YES_PHRASES:
        if phrase in norm:
            return YesNoResult("yes", "phrase")
    for phrase in _NO_PHRASES:
        if phrase in norm:
            return YesNoResult("no", "phrase")

    # 2) Palavras isoladas — tokenize e check exato
    tokens = re.findall(r"\b\w+\b", norm)
    if not tokens:
        return YesNoResult("unknown", "none")

    yes_hits = sum(1 for t in tokens if t in _YES_WORDS)
    no_hits = sum(1 for t in tokens if t in _NO_WORDS)

    if yes_hits > no_hits:
        return YesNoResult("yes", "word")
    if no_hits > yes_hits:
        return YesNoResult("no", "word")
    if yes_hits == no_hits and yes_hits > 0:
        # Empate: olha o ÚLTIMO token (intenção final)
        for t in reversed(tokens):
            if t in _YES_WORDS:
                return YesNoResult("yes", "word")
            if t in _NO_WORDS:
                return YesNoResult("no", "word")

    return YesNoResult("unknown", "none")


def _normalize(text: str) -> str:
    """Lowercase, sem acentos, sem pontuação extra."""
    if not text:
        return ""
    # Remove acentos
    nfkd = unicodedata.normalize("NFD", text.lower())
    cleaned = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Remove pontuação básica (preserva espaços para tokenizar)
    cleaned = re.sub(r"[!?.,;:'\"\(\)\[\]]", " ", cleaned)
    # Colapsa whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned
