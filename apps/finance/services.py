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
def generate_entry_from_lead_won(lead, *, first_due_date=None, notify=True):
    """RV06 — Gera FinancialEntry quando Lead vai para etapa de ganho.

    Cenário: negócio fechado direto via WhatsApp/conversa, SEM proposta
    ou contrato formal. Cliente pediu que isso também contabilize como
    entrada futura no financeiro.

    Args:
        lead: Lead a processar
        first_due_date: data de vencimento da entry (default: hoje + 30 dias)
        notify: se False, NÃO chama _notify_lead_won (usado pelo backfill
                em lote para evitar spam de N notificações simultâneas).

    Comportamento:
    - Valor: lead.estimated_value OR lead.servico.default_price OR 0
    - Status: PENDING (cliente edita depois se quiser marcar como pago)
    - Date: hoje + 30 dias (padrão; cliente edita)
    - Idempotência DUPLA:
      a) Se já existe FinancialEntry(related_lead=lead, auto_generated=True)
         retorna existente
      b) Se lead tem proposta aceita com entries auto-geradas, NÃO duplica
         (porque generate_entries_from_proposal já cuidou disso)
    - Valor 0 OK: cria entry vazia para o user editar manualmente
    """
    existing = list(
        FinancialEntry.objects.filter(
            related_lead=lead, auto_generated=True,
        )
    )
    if existing:
        return existing[0]

    # Se há entries auto-geradas vinculadas a propostas DESTE lead, não duplica.
    # IMPORTANTE: usa `all_objects` (inclui soft-deleted) — senão, ao excluir a
    # proposta sem cascata, a entry fica órfã (related_proposal aponta pra
    # soft-deleted) E o lookup esconde a proposta → criava DUPLICATA da entry
    # no próximo save do lead. Bug identificado no pente fino do dia.
    from apps.proposals.models import Proposal
    proposal_with_entries = (
        Proposal.all_objects.filter(
            lead=lead,
            financial_entries__auto_generated=True,
        ).exists()
    )
    if proposal_with_entries:
        return None  # proposta já cuidou disso

    # Resolve valor
    amount = lead.estimated_value
    if (amount is None or amount <= 0) and lead.servico_id:
        amount = lead.servico.default_price or Decimal("0.00")
    if amount is None:
        amount = Decimal("0.00")

    base_date = first_due_date or (timezone.now().date() + timedelta(days=30))
    default_account = _default_account(lead.empresa)

    notes_extra = ""
    if amount <= 0:
        notes_extra = (
            "\n\n⚠ Valor não definido — edite este lançamento e informe o "
            "valor real do negócio fechado."
        )

    entry = FinancialEntry.objects.create(
        empresa=lead.empresa,
        type=FinancialEntry.Type.INCOME,
        description=f"Lead - {lead.name}",
        amount=amount,
        date=base_date,
        status=FinancialEntry.Status.PENDING,
        related_lead=lead,
        bank_account=default_account,
        auto_generated=True,
        notes=(
            f"Gerado automaticamente — Lead movido para etapa de ganho.{notes_extra}"
        ),
    )
    # RV06 — Notifica responsável (best-effort, não bloqueia).
    # RV10 — backfill em lote passa notify=False pra evitar spam de N
    # notificações simultâneas quando processa empresa com vários leads.
    if notify:
        _notify_lead_won(lead, entry)
    return entry


def _notify_lead_won(lead, entry):
    """RV06 — Notifica responsável (lead.assigned_to) ou todos os membros
    ativos da empresa quando um Lead vai para WON.

    Notification.Type.LEAD_WON com deep-link para o entry no Financeiro.
    Best-effort — qualquer erro é apenas logado.
    """
    try:
        from apps.communications.models import Notification
        from apps.communications.notifications import notify
        from django.urls import reverse

        try:
            url = reverse("finance:entry_update", args=[entry.pk])
        except Exception:  # noqa: BLE001
            url = ""

        amount_fmt = f"R$ {entry.amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        title = f"🎉 Negócio fechado: {lead.name}"
        body = (
            f"Lead movido para etapa de ganho. Entrada de {amount_fmt} criada "
            f"como pendente no Financeiro (vencimento {entry.date.strftime('%d/%m/%Y')})."
        )
        if entry.amount <= 0:
            body += "\n⚠ Valor não definido — edite o lançamento para ajustar."

        payload = {
            "lead_id": lead.pk,
            "entry_id": entry.pk,
            "amount": str(entry.amount),
        }

        # Destinatários: assigned_to OU todos os membros ativos
        recipients = []
        if lead.assigned_to_id:
            recipients.append(lead.assigned_to)
        else:
            from apps.accounts.models import Membership
            recipient_ids = (
                Membership.objects.filter(empresa=lead.empresa, is_active=True)
                .values_list("user_id", flat=True)
            )
            from django.contrib.auth import get_user_model
            recipients = list(
                get_user_model().objects.filter(pk__in=recipient_ids, is_active=True)
            )

        for user in recipients:
            notify(
                user,
                type=Notification.Type.LEAD_WON,
                title=title,
                body=body,
                url=url,
                icon="trophy",
                empresa=lead.empresa,
                payload=payload,
            )
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Erro ao notificar lead_won (lead=%s)", getattr(lead, "pk", None),
        )


def count_won_leads_without_entry(empresa) -> int:
    """RV10 — Conta leads em stage com is_won=True que NÃO têm FinancialEntry.

    Casos detectados:
    - Leads que já estavam em won_stage ANTES do RV06 ser deployado (signal
      só dispara em saves novos).
    - Leads movidos por scripts/imports que setaram `_suppress_finance_entry=True`.
    - Leads cuja proposta gerou entry — esses são EXCLUÍDOS (já contam).

    IMPORTANTE: usa `Proposal.all_objects` (inclui soft-deleted). Senão,
    proposta excluída sem cascata fica invisível na exclusão, e o lead
    aparece como "pendente de lançamento" e ao clicar "Sincronizar agora"
    gera DUPLICATA. Bug identificado no pente fino do dia.
    """
    from apps.crm.models import Lead
    from apps.proposals.models import Proposal

    qs = (
        Lead.objects.filter(
            empresa=empresa,
            pipeline_stage__is_won=True,
        )
        # Não tem entry vinculada direta ao lead
        .exclude(financial_entries__auto_generated=True)
        # Nem tem proposta com entries auto-geradas (a proposta cuidou)
        # — inclusive propostas soft-deletadas (entries órfãs ainda existem)
        .exclude(
            pk__in=Proposal.all_objects.filter(
                empresa=empresa,
                financial_entries__auto_generated=True,
            ).values_list("lead_id", flat=True)
        )
    )
    return qs.count()


def list_won_leads_without_entry(empresa):
    """RV10 — Lista (queryset) dos leads ganhos sem entry. Usado pelo
    dashboard pra mostrar quais leads precisam de atenção.

    Mesmo cuidado do `count_won_leads_without_entry` quanto a soft-deletadas.
    """
    from apps.crm.models import Lead
    from apps.proposals.models import Proposal

    return (
        Lead.objects.filter(
            empresa=empresa,
            pipeline_stage__is_won=True,
        )
        .exclude(financial_entries__auto_generated=True)
        .exclude(
            pk__in=Proposal.all_objects.filter(
                empresa=empresa,
                financial_entries__auto_generated=True,
            ).values_list("lead_id", flat=True)
        )
        .select_related("pipeline_stage", "pipeline_stage__pipeline", "servico")
        .order_by("-updated_at")
    )


def backfill_won_lead_entries(empresa) -> dict:
    """RV10 — Gera FinancialEntry para todos os leads em won_stage sem entry.

    Usado quando o cliente reporta: "fechei 3 negócios este mês mas não
    aparece no financeiro". Causa típica: os leads já estavam em won_stage
    antes do signal RV06 entrar, ou foram movidos por script bypassando o
    signal.

    Retorna {"created": [entry1, ...], "skipped": N, "scanned": N}.
    Idempotente — pode ser rodado várias vezes sem duplicar.

    Hotfix do pente fino: passa `notify=False` para evitar spam de N
    notificações "🎉 Negócio fechado" todas de uma vez (uma por lead × N
    membros ativos). Quem dispara o backfill já viu a mensagem de retorno
    com a contagem total — notificar de novo é ruidoso.
    """
    leads = list(list_won_leads_without_entry(empresa))
    scanned = len(leads)
    created = []
    skipped = 0
    for lead in leads:
        # generate_entry_from_lead_won é idempotente; respeita proposta
        # já paga, valor 0 com warning, etc.
        entry = generate_entry_from_lead_won(lead, notify=False)
        if entry is None:
            skipped += 1
        else:
            created.append(entry)
    return {"created": created, "skipped": skipped, "scanned": scanned}


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
