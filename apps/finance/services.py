"""Serviços de domínio do módulo financeiro.

Regras gerais:
- Idempotência: ao gerar lançamentos a partir de uma proposta/contrato, se já
  existirem lançamentos auto-gerados vinculados, retornamos os existentes sem
  criar duplicatas.
- Rastreabilidade sem acoplamento: os lançamentos ficam marcados com
  ``auto_generated=True`` e mantêm FKs com ``on_delete=SET_NULL``, preservando
  os registros mesmo se proposta/contrato forem removidos, além de permitir
  edição manual livre (valores, datas, status).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import BankAccount, FinancialEntry

DEFAULT_INSTALLMENT_INTERVAL_DAYS = 30


# ---------------------------------------------------------------------------
# Pix / Boleto — stubs preparados para integração futura
# ---------------------------------------------------------------------------
# Arquitetura: cada método recebe um FinancialEntry e a BankAccount associada,
# retorna um dict com os dados gerados. Quando a integração real for conectada,
# basta substituir o corpo desses métodos por chamadas à API do banco/PSP.
# Os dados gerados ficam em entry.payment_ref para rastreabilidade.
# ---------------------------------------------------------------------------


def generate_pix_data(entry, bank_account=None):
    """Gera dados de cobrança Pix para um lançamento.

    STUB: retorna payload simulado. Para integração real, substituir por
    chamada à API do PSP (ex: Gerencianet, Mercado Pago, Asaas, etc.).

    Retorna:
        dict com chaves: qr_code_text, qr_code_image_url, pix_key, amount,
        description, status ('stub').
    """
    account = bank_account or _default_account(entry.empresa)
    pix_key = account.pix_key if account else ""

    payload = {
        "qr_code_text": (
            f"00020126360014BR.GOV.BCB.PIX0114{pix_key}"
            f"5204000053039865802BR"
            f"5913{(account.holder_name or 'Empresa')[:13]}"
            f"6008BRASILIA62070503***6304"
            if pix_key
            else ""
        ),
        "qr_code_image_url": "",  # Integração real geraria imagem
        "pix_key": pix_key,
        "amount": str(entry.amount),
        "description": entry.description[:60],
        "status": "stub",
        "integration_ready": bool(pix_key),
    }

    # Salva referência no entry para rastreabilidade
    if pix_key and not entry.payment_ref:
        entry.payment_ref = f"PIX:{pix_key}"
        entry.save(update_fields=["payment_ref", "updated_at"])

    return payload


def generate_boleto_data(entry, bank_account=None):
    """Gera dados de boleto bancário para um lançamento.

    STUB: retorna payload simulado. Para integração real, substituir por
    chamada à API do banco ou intermediador (ex: BoletoCloud, Asaas, etc.).

    Retorna:
        dict com chaves: barcode, digitable_line, pdf_url, amount,
        due_date, status ('stub').
    """
    account = bank_account or _default_account(entry.empresa)
    bank_code = account.bank_code if account else "000"

    payload = {
        "barcode": f"{bank_code}.00000 00000.000000 00000.000000 0 00000000000000",
        "digitable_line": f"{bank_code}00000000000000000000000000000000000000000000000",
        "pdf_url": "",  # Integração real geraria PDF
        "amount": str(entry.amount),
        "due_date": str(entry.date),
        "bank_name": account.bank_name if account else "",
        "status": "stub",
        "integration_ready": False,
    }

    if not entry.payment_ref:
        entry.payment_ref = f"BOLETO:STUB:{entry.pk}"
        entry.save(update_fields=["payment_ref", "updated_at"])

    return payload


def _default_account(empresa):
    """Retorna a conta padrão da empresa, ou a primeira ativa."""
    return (
        BankAccount.objects.filter(empresa=empresa, is_active=True)
        .order_by("-is_default", "pk")
        .first()
    )


@transaction.atomic
def generate_entries_from_proposal(
    proposal,
    *,
    first_due_date=None,
    interval_days: int = DEFAULT_INSTALLMENT_INTERVAL_DAYS,
):
    """Gera lançamentos financeiros a partir de uma proposta aceita.

    - Não parcelada: cria 1 lançamento pendente no valor total.
    - Parcelada: cria N lançamentos com vencimentos escalonados.
    - Idempotente: retorna os lançamentos existentes se já houver
      ``auto_generated=True`` vinculado à proposta.
    - Valor <= 0: retorna lista vazia (sem erro).
    """
    existing = list(
        FinancialEntry.objects.filter(
            related_proposal=proposal, auto_generated=True
        )
    )
    if existing:
        return existing

    total = Decimal(proposal.total or 0)
    if total <= 0:
        return []

    count = (
        int(proposal.installment_count or 1)
        if proposal.is_installment
        else 1
    )
    if count < 1:
        count = 1

    base_date = first_due_date or timezone.now().date()
    per_installment = (total / count).quantize(Decimal("0.01"))
    default_account = _default_account(proposal.empresa)

    entries: list[FinancialEntry] = []
    accumulated = Decimal("0.00")
    for i in range(count):
        is_last = i == count - 1
        # Última parcela recebe o restante para garantir soma exata
        amount = (total - accumulated) if is_last else per_installment
        accumulated += amount
        due_date = base_date + timedelta(days=interval_days * i)
        suffix = f" ({i + 1}/{count})" if count > 1 else ""

        entry = FinancialEntry.objects.create(
            empresa=proposal.empresa,
            type=FinancialEntry.Type.INCOME,
            description=f"{proposal.number} - {proposal.title}{suffix}",
            amount=amount,
            date=due_date,
            status=FinancialEntry.Status.PENDING,
            related_proposal=proposal,
            bank_account=default_account,
            auto_generated=True,
            notes=(
                f"Gerado automaticamente a partir da proposta "
                f"{proposal.number}."
            ),
        )
        entries.append(entry)

    return entries
