"""Matcher unificado de opções de menu (simulator + executor V2 + V1 legacy).

Bug histórico: usuário clica em quick-reply "1 Solicitar orçamento" e o bot
responde "Não entendi" porque o matcher só aceitava número puro OU label
exato. Os formatos reais que aparecem na prática são MUITOS:

- `1` (só número)
- `Solicitar orçamento` (label exato)
- `solicitar orçamento` (case-insensitive)
- `1 Solicitar orçamento` (número + label, comum no WhatsApp)
- `1. Solicitar orçamento` (com ponto)
- `1) Solicitar orçamento` (com parêntese)
- `1️⃣ Solicitar orçamento` (emoji keycap)
- `opt_1` (handle_id, quando o cliente envia diretamente)
- `solicit` (prefixo do label)

Este módulo centraliza essa lógica. Tudo que precisa fazer match é chamar
`match_menu_choice(options, text) -> MatchResult | None`.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Emoji keycaps: 1️⃣, 2️⃣, ... 0️⃣
_KEYCAP_TO_DIGIT = {
    "1️⃣": "1", "2️⃣": "2", "3️⃣": "3", "4️⃣": "4", "5️⃣": "5",
    "6️⃣": "6", "7️⃣": "7", "8️⃣": "8", "9️⃣": "9", "0️⃣": "0",
}

# Regex: prefixo numérico opcional seguido por separadores
# Aceita: "1", "1.", "1)", "1 -", "1️⃣ ", "1 " etc.
_NUM_PREFIX_RE = re.compile(
    r"^\s*"
    r"(?P<num>\d+)"
    r"\s*[\.\)\:\-—–]?"  # opcional ponto, parêntese, etc
    r"\s+"
    r"(?P<rest>.+)$"
)


@dataclass
class MatchResult:
    """Resultado de um match bem-sucedido."""
    handle_id: str
    label: str
    matched_by: str  # "number", "label", "value", "prefix", "substring"


def match_menu_choice(options: list[dict], text: str) -> MatchResult | None:
    """Encontra a opção que case com o texto do usuário.

    Aceita múltiplos formatos (ver docstring do módulo). Retorna None se
    nenhuma opção bateu. Não levanta exceção.

    Args:
        options: lista de dicts com keys 'label', 'handle_id' (e opcional 'value')
        text: resposta crua do usuário (qualquer string)
    """
    if not options:
        return None

    # Normaliza whitespace: NBSP (\xa0), ZWSP (​), tab → espaço normal
    raw = _clean_whitespace(text or "").strip()
    if not raw:
        return None

    # 0) Normaliza emoji keycap → número equivalente no INÍCIO da string
    normalized = raw
    for keycap, digit in _KEYCAP_TO_DIGIT.items():
        if normalized.startswith(keycap):
            normalized = digit + " " + normalized[len(keycap):].lstrip()
            break

    # 1) Match exato por handle_id (caso o frontend envie value direto)
    for opt in options:
        hid = opt.get("handle_id") or ""
        if normalized == hid:
            return MatchResult(
                handle_id=hid,
                label=opt.get("label") or hid,
                matched_by="handle_id",
            )

    # 2) Tenta tratar como número puro (1, 2, 3...)
    try:
        idx = int(normalized) - 1
        if 0 <= idx < len(options):
            opt = options[idx]
            return MatchResult(
                handle_id=opt.get("handle_id") or "",
                label=opt.get("label") or "",
                matched_by="number",
            )
    except (ValueError, TypeError):
        pass

    # 3) Tenta extrair número de prefixo "N Label" / "N. Label" / "N) Label"
    m = _NUM_PREFIX_RE.match(normalized)
    if m:
        try:
            idx = int(m.group("num")) - 1
            if 0 <= idx < len(options):
                # Confirma que o "rest" bate com o label (defesa contra
                # números espúrios — ex.: "20 anos" não deveria selecionar opção 20)
                rest = _normalize_for_compare(m.group("rest"))
                opt_label = _normalize_for_compare(options[idx].get("label") or "")
                # Match se o resto for substring ou começa com o label
                if rest and (
                    rest == opt_label
                    or opt_label.startswith(rest)
                    or rest.startswith(opt_label)
                ):
                    opt = options[idx]
                    return MatchResult(
                        handle_id=opt.get("handle_id") or "",
                        label=opt.get("label") or "",
                        matched_by="number_with_label",
                    )
                # Senão, ainda assim aceita pelo número se o rest é curto
                # (talvez o user tenha digitado label parcial)
                if len(rest) <= 3:
                    opt = options[idx]
                    return MatchResult(
                        handle_id=opt.get("handle_id") or "",
                        label=opt.get("label") or "",
                        matched_by="number",
                    )
        except (ValueError, TypeError):
            pass

    # 4) Match exato por label (case + accent insensitive)
    text_norm = _normalize_for_compare(normalized)
    for opt in options:
        label_norm = _normalize_for_compare(opt.get("label") or "")
        value_norm = _normalize_for_compare(opt.get("value") or "")
        # Também aceita label SEM o prefixo numérico (ex: user digita
        # "Solicitar orçamento" e o label é "1️⃣ Solicitar orçamento")
        label_norm_no_prefix = _strip_num_prefix(label_norm)
        if text_norm and (
            text_norm == label_norm
            or text_norm == value_norm
            or text_norm == label_norm_no_prefix
        ):
            return MatchResult(
                handle_id=opt.get("handle_id") or "",
                label=opt.get("label") or "",
                matched_by="label",
            )

    # 5) Match por prefixo (text é início do label, >= 3 chars)
    if len(text_norm) >= 3:
        for opt in options:
            label_norm = _normalize_for_compare(opt.get("label") or "")
            label_norm_no_prefix = _strip_num_prefix(label_norm)
            if label_norm.startswith(text_norm) or label_norm_no_prefix.startswith(text_norm):
                return MatchResult(
                    handle_id=opt.get("handle_id") or "",
                    label=opt.get("label") or "",
                    matched_by="prefix",
                )

    # 6) Match por substring — útil para mensagens conversacionais
    # ("eu quero solicitar um orçamento" deveria matchar "Solicitar orçamento")
    if len(text_norm) >= 4:
        for opt in options:
            label_norm = _normalize_for_compare(opt.get("label") or "")
            if label_norm and label_norm in text_norm:
                return MatchResult(
                    handle_id=opt.get("handle_id") or "",
                    label=opt.get("label") or "",
                    matched_by="substring",
                )

    return None


def _normalize_for_compare(text: str) -> str:
    """Lowercase + remove acentos + normaliza whitespace + substitui keycap emojis.

    RV06 — Aplicar substituição de keycap (1️⃣→1) em AMBOS os lados (input
    E label). Antes, só fazia no input — então label '1️⃣ Solicitar' nunca
    casava com '1 Solicitar' do user normalizado.
    """
    if not text:
        return ""
    # Substitui TODOS os keycaps por dígito + espaço (não só no início)
    out = text
    for keycap, digit in _KEYCAP_TO_DIGIT.items():
        out = out.replace(keycap, digit + " ")
    cleaned = _clean_whitespace(out.lower())
    # Remove acentos (NFD decompõe; filtra combining chars)
    nfkd = unicodedata.normalize("NFD", cleaned)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip()


def _strip_num_prefix(text: str) -> str:
    """Remove prefixo numérico opcional do label normalizado.

    'solicitar orcamento'        -> 'solicitar orcamento' (sem mudança)
    '1 solicitar orcamento'      -> 'solicitar orcamento'
    '1. solicitar orcamento'     -> 'solicitar orcamento'
    '1) solicitar orcamento'     -> 'solicitar orcamento'
    """
    m = _NUM_PREFIX_RE.match(text)
    if m:
        return m.group("rest").strip()
    return text


def _clean_whitespace(text: str) -> str:
    """Substitui caracteres invisíveis problemáticos por espaço normal.

    Cobre: NBSP (\\xa0), ZWSP (\\u200b), zero-width non-joiner (\\u200c),
    zero-width joiner (\\u200d), word joiner (\\u2060), em space (\\u2003),
    tabs, etc. Sem isso, "1 Solicitar orçamento" copiado de Word ou de
    alguns navegadores tem NBSP entre o "1" e o resto, e falha o match.
    """
    if not text:
        return ""
    INVISIBLE = "\xa0​‌‍⁠     　"
    for ch in INVISIBLE:
        text = text.replace(ch, " ")
    # Normaliza tabs e múltiplos espaços para 1 só
    text = re.sub(r"[\t ]+", " ", text)
    return text
