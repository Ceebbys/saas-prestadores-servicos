"""RV08 (6.1) — Open Finance: importação e classificação de movimentações.

MVP entregável HOJE:
- Importação manual de extrato **CSV/OFX** (funciona sem credenciais).
- Provider **sandbox** que gera movimentações de demonstração.
- Interface ``OpenFinanceProvider`` plugável: Pluggy/Belvo entram depois via
  ``settings.OPEN_FINANCE_PROVIDER``, reusando ``import_transactions`` +
  ``classify_transaction``.

Fluxo: extrato/agregador → ``import_transactions`` (idempotente por external_id)
→ inbox de classificação → ``classify_transaction`` gera um ``FinancialEntry``.
"""
from __future__ import annotations

import abc
import csv
import hashlib
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import FinancialEntry, ImportedTransaction


# ---------------------------------------------------------------------------
# Provider plugável
# ---------------------------------------------------------------------------


class OpenFinanceProvider(abc.ABC):
    """Contrato de um provedor de movimentações (sandbox, Pluggy, Belvo…)."""

    name: str = "base"

    @abc.abstractmethod
    def fetch_transactions(self, *, date_from: date | None = None) -> list[dict]:
        """Retorna linhas normalizadas (ver ``import_transactions``)."""
        raise NotImplementedError


class SandboxProvider(OpenFinanceProvider):
    """Provider de demonstração: gera algumas movimentações fictícias.

    Permite testar o fluxo ponta-a-ponta (conectar → importar → classificar)
    sem credenciais reais. As datas são relativas a hoje para parecerem atuais.
    """

    name = "sandbox"

    def fetch_transactions(self, *, date_from: date | None = None) -> list[dict]:
        today = timezone.now().date()

        def d(days_ago):
            return today.fromordinal(today.toordinal() - days_ago)

        samples = [
            (2, "PIX RECEBIDO - CLIENTE TOPOGRAFIA", Decimal("1500.00"), "credit"),
            (3, "TARIFA BANCARIA MENSAL", Decimal("39.90"), "debit"),
            (5, "TED RECEBIDA - SERVICO REGULARIZACAO", Decimal("3200.00"), "credit"),
            (6, "PAGAMENTO FORNECEDOR - MATERIAL", Decimal("450.00"), "debit"),
            (9, "PIX RECEBIDO - ENTRADA PROJETO", Decimal("800.00"), "credit"),
        ]
        rows = []
        for idx, (days, desc, amount, direction) in enumerate(samples):
            txn_date = d(days)
            rows.append({
                "external_id": f"sandbox-{txn_date.isoformat()}-{idx}",
                "date": txn_date,
                "amount": amount,
                "description": desc,
                "direction": direction,
                "raw": {"provider": "sandbox"},
            })
        return rows


def get_provider(name: str | None = None) -> OpenFinanceProvider | None:
    """Factory simples. Hoje só ``sandbox``. Pluggy/Belvo entram aqui depois."""
    from django.conf import settings

    name = (name or getattr(settings, "OPEN_FINANCE_PROVIDER", "sandbox") or "sandbox").lower()
    if name == "sandbox":
        return SandboxProvider()
    # PLUGGY/BELVO: instanciar o provider real quando as credenciais existirem.
    return None


# ---------------------------------------------------------------------------
# Parsers de extrato (CSV / OFX)
# ---------------------------------------------------------------------------


def _parse_amount(raw) -> Decimal | None:
    """Aceita '1.234,56', '1234.56', '-50,00', números. Retorna Decimal (com sinal)."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float, Decimal)):
        try:
            return Decimal(str(raw))
        except InvalidOperation:
            return None
    s = str(raw).strip().replace("R$", "").replace(" ", "")
    if not s:
        return None
    # Formato brasileiro: vírgula decimal + ponto de milhar.
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _parse_date(raw) -> date | None:
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _row_external_id(provided, txn_date, desc, amount, idx) -> str:
    if provided:
        return str(provided)[:200]
    base = f"{txn_date}|{desc}|{amount}|{idx}"
    return "csv-" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:24]


def parse_csv(content: str) -> list[dict]:
    """Parser de CSV de extrato. Colunas (case-insensitive, PT ou EN):
    data/date, descricao/description/historico/memo, valor/amount e opcional id.
    Sem cabeçalho: assume ordem [data, descricao, valor]. Delimitador ; ou ,."""
    text = content.lstrip("﻿")
    sample = text[:2048]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        return []

    header = [c.strip().lower() for c in rows[0]]
    has_header = any(
        h in {"data", "date", "valor", "amount", "descricao", "descrição",
              "description", "historico", "histórico", "memo"}
        for h in header
    )

    def col(idx_names, default_idx):
        for nm in idx_names:
            if nm in header:
                return header.index(nm)
        return default_idx

    if has_header:
        i_date = col(["data", "date"], 0)
        i_desc = col(["descricao", "descrição", "description", "historico", "histórico", "memo"], 1)
        i_amount = col(["valor", "amount", "value"], 2)
        i_id = col(["id", "fitid", "identificador"], -1)
        data_rows = rows[1:]
    else:
        i_date, i_desc, i_amount, i_id = 0, 1, 2, -1
        data_rows = rows

    out = []
    seen_keys: dict[tuple, int] = {}
    for r in data_rows:
        # RV08 — Proteção contra CSV vírgula-delimitado COM decimais por vírgula
        # (ex.: "...,1500,50"): o valor é quebrado pelo separador decimal e a
        # linha fica com mais campos que o cabeçalho. Em vez de gravar um valor
        # corrompido silenciosamente, pulamos a linha. (Extratos BR devem usar
        # ';' como separador — esse caso é parseado corretamente.)
        if has_header and len(r) > len(header):
            continue
        if len(r) <= max(i_date, i_amount):
            continue
        txn_date = _parse_date(r[i_date])
        amount = _parse_amount(r[i_amount])
        if txn_date is None or amount is None:
            continue
        desc = (r[i_desc].strip() if 0 <= i_desc < len(r) else "")[:500]
        provided_id = r[i_id].strip() if (0 <= i_id < len(r)) else ""
        # Sem id do banco: usa um contador de ocorrência por (data, desc, valor)
        # para que o external_id seja ESTÁVEL entre reimportações do mesmo
        # extrato — mesmo que outras linhas tenham sido adicionadas/removidas
        # (a posição na lista não pode ser usada).
        key = (txn_date.isoformat(), desc, str(amount))
        occ = seen_keys.get(key, 0)
        seen_keys[key] = occ + 1
        out.append({
            "external_id": _row_external_id(provided_id, txn_date, desc, amount, occ),
            "date": txn_date,
            "amount": amount,
            "description": desc,
            "raw": {"source": "csv"},
        })
    return out


_OFX_TXN_RE = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.DOTALL | re.IGNORECASE)


def _ofx_tag(block, tag):
    m = re.search(rf"<{tag}>([^<\r\n]*)", block, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def parse_ofx(content: str) -> list[dict]:
    """Parser mínimo de OFX (SGML): extrai blocos <STMTTRN> sem libs externas."""
    out = []
    for idx, block in enumerate(_OFX_TXN_RE.findall(content or "")):
        amount = _parse_amount(_ofx_tag(block, "TRNAMT"))
        txn_date = _parse_date(_fmt_ofx_date(_ofx_tag(block, "DTPOSTED")))
        if amount is None or txn_date is None:
            continue
        desc = (_ofx_tag(block, "MEMO") or _ofx_tag(block, "NAME"))[:500]
        fitid = _ofx_tag(block, "FITID")
        out.append({
            "external_id": _row_external_id(fitid, txn_date, desc, amount, idx),
            "date": txn_date,
            "amount": amount,
            "description": desc,
            "raw": {"source": "ofx"},
        })
    return out


def _fmt_ofx_date(raw: str) -> str:
    """OFX DTPOSTED vem como YYYYMMDD[HHMMSS] → YYYY-MM-DD."""
    digits = re.sub(r"\D", "", raw or "")[:8]
    if len(digits) == 8:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    return raw


def parse_statement(filename: str, content: bytes) -> list[dict]:
    """Decide CSV vs OFX pela extensão/conteúdo e delega ao parser."""
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    lower = (filename or "").lower()
    if lower.endswith(".ofx") or "<OFX>" in text.upper() or "<STMTTRN>" in text.upper():
        return parse_ofx(text)
    return parse_csv(text)


# ---------------------------------------------------------------------------
# Importação + classificação
# ---------------------------------------------------------------------------


@transaction.atomic
def import_transactions(empresa, rows, *, connection=None, bank_account=None) -> dict:
    """Importa linhas normalizadas como ImportedTransaction (idempotente).

    Cada ``row``: ``{external_id, date, amount, description, direction?, raw?}``.
    ``amount`` pode vir com sinal (negativo = débito) ou ``direction`` explícito.
    Retorna ``{"created": int, "skipped": int}``.
    """
    created = skipped = 0
    for row in rows:
        external_id = (row.get("external_id") or "").strip()
        # RV08 — coage/valida a data (a API pública pode receber string do
        # Pluggy/Belvo); pula a linha se não der uma data válida (em vez de
        # estourar um DataError no meio do batch).
        txn_date = row.get("date")
        if not isinstance(txn_date, date):
            txn_date = _parse_date(txn_date) if txn_date else None
        amount = row.get("amount")
        if not external_id or txn_date is None or amount is None:
            skipped += 1
            continue
        try:
            amount = amount if isinstance(amount, Decimal) else Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError):
            skipped += 1
            continue
        direction = row.get("direction")
        if direction not in ("credit", "debit"):
            direction = "debit" if amount < 0 else "credit"
        abs_amount = abs(amount).quantize(Decimal("0.01"))

        _obj, was_created = ImportedTransaction.objects.get_or_create(
            empresa=empresa,
            external_id=external_id,
            defaults={
                "connection": connection,
                "bank_account": bank_account or (connection.bank_account if connection else None),
                "date": txn_date,
                "amount": abs_amount,
                "description": (row.get("description") or "")[:500],
                "direction": direction,
                "raw_payload": row.get("raw") or {},
            },
        )
        created += 1 if was_created else 0
        skipped += 0 if was_created else 1

    if connection is not None:
        connection.last_synced_at = timezone.now()
        connection.save(update_fields=["last_synced_at", "updated_at"])

    return {"created": created, "skipped": skipped}


@transaction.atomic
def classify_transaction(
    txn: ImportedTransaction,
    *,
    entry_type: str,
    category=None,
    related_work_order=None,
    related_lead=None,
) -> FinancialEntry:
    """Classifica a movimentação criando um FinancialEntry e vinculando-a.

    Idempotente: se já classificada, devolve o lançamento existente.
    O lançamento nasce como PAGO na data da movimentação (regime de caixa).
    """
    if txn.classification_status == ImportedTransaction.Status.CLASSIFIED and txn.classified_entry_id:
        return txn.classified_entry

    entry = FinancialEntry.objects.create(
        empresa=txn.empresa,
        type=entry_type,
        description=txn.description or "Movimentação importada",
        amount=txn.amount,
        date=txn.date,
        paid_date=txn.date,
        status=FinancialEntry.Status.PAID,
        category=category,
        bank_account=txn.bank_account,
        related_work_order=related_work_order,
        related_lead=related_lead,
        auto_generated=True,
        notes="Classificada a partir de movimentação importada (Open Finance / RV08 6.1).",
        payment_ref=f"OF:{txn.external_id}"[:200],
    )
    txn.classification_status = ImportedTransaction.Status.CLASSIFIED
    txn.classified_entry = entry
    txn.save(update_fields=["classification_status", "classified_entry", "updated_at"])
    return entry
