from datetime import date

from django.contrib import messages
from django.db.models import Case, F, Q, Sum, When
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView,
    ListView,
    TemplateView,
    UpdateView,
)

from apps.core.mixins import EmpresaMixin, HtmxResponseMixin

from .forms import FinancialCategoryForm, FinancialEntryForm
from .models import (
    BankAccount,
    BankConnection,
    FinancialCategory,
    FinancialEntry,
    ImportedTransaction,
)


# ---------------------------------------------------------------------------
# Finance Overview
# ---------------------------------------------------------------------------

# RV07 — Períodos do dashboard financeiro (item 1.3).
FINANCE_PERIOD_CHOICES = [
    ("mes_atual", "Mês atual"),
    ("3m", "Últimos 3 meses"),
    ("6m", "Últimos 6 meses"),
    ("12m", "Últimos 12 meses"),
    ("ano", "Ano atual"),
    ("tudo", "Todo o período"),
]


def _finance_period_range(period, today, selected_month=None):
    """Retorna (start, end, label) para o filtro de período do dashboard.

    ``start``/``end`` ``None`` => sem limite naquela ponta (todo o período).
    Os intervalos de N meses são por mês-calendário, incluindo o mês atual.
    ``period == "mes"`` + ``selected_month`` ('YYYY-MM') filtra um mês específico
    (cliente pediu "vê o mês q vc quiser").
    """
    import calendar

    def _last_day(year, month):
        return date(year, month, calendar.monthrange(year, month)[1])

    def _add_months(year, month, delta):
        idx = (year * 12 + (month - 1)) + delta
        return idx // 12, idx % 12 + 1

    # RV07 — Mês específico (filtro mensal).
    if period == "mes" and selected_month:
        try:
            year_str, month_str = selected_month.split("-")
            year, month = int(year_str), int(month_str)
            if 1 <= month <= 12 and 2000 <= year <= 2100:
                pt_full = [
                    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
                ]
                return (
                    date(year, month, 1),
                    _last_day(year, month),
                    f"{pt_full[month - 1]}/{year}",
                )
        except (ValueError, TypeError, AttributeError):
            pass  # mês inválido → cai para o mês atual abaixo

    if period == "tudo":
        return None, None, "Todo o período"
    if period == "ano":
        return date(today.year, 1, 1), _last_day(today.year, 12), f"Ano de {today.year}"
    if period in ("3m", "6m", "12m"):
        n = int(period[:-1])
        start_year, start_month = _add_months(today.year, today.month, -(n - 1))
        return (
            date(start_year, start_month, 1),
            _last_day(today.year, today.month),
            f"Últimos {n} meses",
        )
    # default: mês atual
    return (
        date(today.year, today.month, 1),
        _last_day(today.year, today.month),
        "Mês atual",
    )


class FinanceOverviewView(EmpresaMixin, HtmxResponseMixin, TemplateView):
    template_name = "finance/overview.html"
    partial_template_name = "finance/partials/_overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = date.today()
        empresa = self.request.empresa

        # RV07 — Filtro de período do dashboard. Cliente pediu: "tem q ter
        # como filtra para vê o mês q vc quiser e tbm ter a visão de todo o
        # período e não ir trocando os dados do dashboard". Os cards (receitas/
        # despesas/saldo/pendentes) passam a respeitar o período; a Previsão de
        # receita continua consolidada (olha sempre pra frente).
        import re

        period = self.request.GET.get("period", "mes_atual")
        selected_month = self.request.GET.get("mes", "").strip()
        valid_periods = {p for p, _ in FINANCE_PERIOD_CHOICES} | {"mes"}
        if period not in valid_periods:
            period = "mes_atual"
        # period=mes exige um mês 'YYYY-MM' válido (01-12); senão volta ao mês atual.
        if period == "mes" and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", selected_month):
            period, selected_month = "mes_atual", ""
        period_start, period_end, period_label = _finance_period_range(
            period, today, selected_month,
        )

        # RV07 — Data contábil (regime de caixa): lançamentos PAGOS contam pela
        # DATA DE PAGAMENTO (quando o dinheiro entrou/saiu); pendentes/vencidos
        # pela data de vencimento (projeção). Cliente reportou que uma despesa
        # paga em maio mas com vencimento em junho estava sendo contada em junho.
        period_entries = FinancialEntry.objects.filter(empresa=empresa).annotate(
            acct_date=Case(
                When(
                    status=FinancialEntry.Status.PAID,
                    then=Coalesce("paid_date", "date"),
                ),
                default=F("date"),
            )
        )
        if period_start:
            period_entries = period_entries.filter(acct_date__gte=period_start)
        if period_end:
            period_entries = period_entries.filter(acct_date__lte=period_end)

        # RV10 — Cliente reportou "fiz 3 despesas mas só conta 2". A SOMA
        # estava correta, mas a lista de "Recentes" mostra só top-10 — o
        # 3º lançamento estava fora. Agora mostramos contagem + breakdown
        # PAGO/PENDENTE no card pra reduzir a confusão.
        from django.db.models import Count

        income_paid = period_entries.filter(
            type=FinancialEntry.Type.INCOME,
            status=FinancialEntry.Status.PAID,
        ).aggregate(total=Sum("amount"), count=Count("id"))
        total_income = income_paid.get("total") or 0
        income_paid_count = income_paid.get("count") or 0

        income_pending = period_entries.filter(
            type=FinancialEntry.Type.INCOME,
            status=FinancialEntry.Status.PENDING,
        ).aggregate(total=Sum("amount"), count=Count("id"))
        income_pending_total = income_pending.get("total") or 0
        income_pending_count = income_pending.get("count") or 0

        expense_paid = period_entries.filter(
            type=FinancialEntry.Type.EXPENSE,
            status=FinancialEntry.Status.PAID,
        ).aggregate(total=Sum("amount"), count=Count("id"))
        total_expense = expense_paid.get("total") or 0
        expense_paid_count = expense_paid.get("count") or 0

        expense_pending = period_entries.filter(
            type=FinancialEntry.Type.EXPENSE,
            status=FinancialEntry.Status.PENDING,
        ).aggregate(total=Sum("amount"), count=Count("id"))
        expense_pending_total = expense_pending.get("total") or 0
        expense_pending_count = expense_pending.get("count") or 0

        balance = total_income - total_expense

        # RV10 — Pendentes quebrado em receitas vs despesas (era só count plano)
        pending_count = income_pending_count + expense_pending_count

        overdue_count = FinancialEntry.objects.filter(
            empresa=empresa,
            status=FinancialEntry.Status.PENDING,
            date__lt=today,
        ).count()

        recent_entries = (
            FinancialEntry.objects.filter(empresa=empresa)
            .select_related(
                "category", "bank_account",
                "related_proposal", "related_contract", "related_work_order",
            )
            .order_by("-date", "-created_at")[:10]
        )

        bank_accounts = BankAccount.objects.filter(
            empresa=empresa, is_active=True
        )

        # RV06 — Previsão de receita: agrupa entries pendentes (auto-geradas
        # OU manuais com type=INCOME) por mês de vencimento. Últimos 6 meses.
        forecast = _compute_revenue_forecast(empresa, today, months=6)
        # RV10 — Cliente pediu: "deve puxar dos dois. Quando tiver fechado
        # ganho, mas sem proposta e contrato puxa direto do lead, se tiver
        # proposta ai puxa da proposta". A lógica já é essa (idempotência do
        # generate_entry_from_lead_won impede duplicação). Aqui só tornamos
        # explícito mostrando QUANTO vem de cada origem no breakdown.
        forecast_breakdown = _compute_forecast_breakdown(empresa, today, months=6)

        # RV10 — Cliente reportou: "fechei 3 leads sem proposta mas não
        # aparecem na previsão". Causa típica: leads já estavam em won_stage
        # antes do signal RV06, ou movidos via script. Aqui contamos e
        # listamos para o dashboard, e oferecemos botão "Sincronizar agora".
        from .services import count_won_leads_without_entry, list_won_leads_without_entry
        won_leads_pending = count_won_leads_without_entry(empresa)
        won_leads_pending_preview = (
            list(list_won_leads_without_entry(empresa)[:5])
            if won_leads_pending else []
        )
        # RV10 hotfix — quantos sobram além dos 5 do preview (corrige bug
        # "…e mais -5" no banner que vinha da combinação errada de filtros
        # `add` + `length` no template)
        won_leads_pending_remaining = max(0, won_leads_pending - 5)

        # RV10 — Detecta também entries com valor 0 (criadas com warning
        # porque lead não tinha estimated_value nem servico). Cliente
        # provavelmente quer ajustar esses valores.
        zero_value_entries_count = FinancialEntry.objects.filter(
            empresa=empresa,
            auto_generated=True,
            amount=0,
            status=FinancialEntry.Status.PENDING,
            related_lead__isnull=False,
        ).count()

        context.update(
            {
                "total_income": total_income,
                "income_paid_count": income_paid_count,
                "income_pending_total": income_pending_total,
                "income_pending_count": income_pending_count,
                "total_expense": total_expense,
                "expense_paid_count": expense_paid_count,
                "expense_pending_total": expense_pending_total,
                "expense_pending_count": expense_pending_count,
                "balance": balance,
                "pending_count": pending_count,
                "overdue_count": overdue_count,
                "recent_entries": recent_entries,
                "current_month": today,
                "current_period": period,
                "period_label": period_label,
                "period_choices": FINANCE_PERIOD_CHOICES,
                "selected_month": selected_month,
                "bank_accounts": bank_accounts,
                "forecast_months": forecast["months"],
                "forecast_total": forecast["total"],
                "forecast_max": forecast["max"],
                "forecast_breakdown": forecast_breakdown,
                "won_leads_pending": won_leads_pending,
                "won_leads_pending_preview": won_leads_pending_preview,
                "won_leads_pending_remaining": won_leads_pending_remaining,
                "zero_value_entries_count": zero_value_entries_count,
            }
        )
        return context


def _compute_revenue_forecast(empresa, today, *, months: int = 6) -> dict:
    """RV06 — Previsão de receita (FinancialEntry pendente) por mês.

    Considera APENAS type=INCOME e status in (PENDING, OVERDUE) —
    receitas confirmadas (PAID) já estão no caixa. Inclui auto-gerados
    de propostas/leads E lançamentos manuais.

    Args:
        empresa: tenant
        today: data de referência (geralmente hoje)
        months: quantos meses à frente (default 6)

    Returns:
        {
            "months": [{"label": "Maio/26", "year": 2026, "month": 5, "total": Decimal, "count": int}, ...],
            "total": Decimal (soma de todos os meses),
            "max": Decimal (maior mês — usado pra escalar gráfico),
        }
    """
    from datetime import date as _date
    from decimal import Decimal

    # Constrói lista de (ano, mês) dos próximos N meses, começando do mês atual
    pairs: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(months):
        pairs.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1

    qs = FinancialEntry.objects.filter(
        empresa=empresa,
        type=FinancialEntry.Type.INCOME,
        status__in=(
            FinancialEntry.Status.PENDING,
            FinancialEntry.Status.OVERDUE,
        ),
    )

    pt_months = [
        "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
        "Jul", "Ago", "Set", "Out", "Nov", "Dez",
    ]
    months_out: list[dict] = []
    total = Decimal("0.00")
    max_val = Decimal("0.00")
    for (year, month) in pairs:
        month_total = (
            qs.filter(date__year=year, date__month=month)
            .aggregate(total=Sum("amount"))["total"]
        ) or Decimal("0.00")
        count = qs.filter(date__year=year, date__month=month).count()
        months_out.append({
            "label": f"{pt_months[month - 1]}/{year % 100:02d}",
            "year": year,
            "month": month,
            "total": month_total,
            "count": count,
        })
        total += month_total
        if month_total > max_val:
            max_val = month_total
    return {"months": months_out, "total": total, "max": max_val}


def _compute_forecast_breakdown(empresa, today, *, months: int = 6) -> dict:
    """RV10 — Quebra a previsão por ORIGEM do lançamento.

    Cliente pediu: "deve puxar dos dois. Quando tiver fechado ganho, mas
    sem proposta e contrato puxa direto do lead, se tiver proposta ai puxa
    da proposta". A lógica já é essa (idempotência impede duplicação no
    `generate_entry_from_lead_won`). Aqui só explicitamos QUANTO vem de
    cada fonte pra dar tranquilidade ao user.

    Returns:
        {
            "from_proposal": {"total": Decimal, "count": int},
            "from_lead": {"total": Decimal, "count": int},
            "manual": {"total": Decimal, "count": int},
        }
    Range de datas: do mês atual até `months` meses à frente.
    """
    from decimal import Decimal

    # Calcula fim do range (último dia do mês N à frente)
    y_end, m_end = today.year, today.month
    for _ in range(months - 1):
        m_end += 1
        if m_end > 12:
            m_end = 1
            y_end += 1
    # Fim = primeiro dia do mês seguinte ao último incluído
    next_m_end = m_end + 1
    next_y_end = y_end
    if next_m_end > 12:
        next_m_end = 1
        next_y_end += 1
    from datetime import date as _date
    range_end = _date(next_y_end, next_m_end, 1)
    range_start = _date(today.year, today.month, 1)

    base_qs = FinancialEntry.objects.filter(
        empresa=empresa,
        type=FinancialEntry.Type.INCOME,
        status__in=(
            FinancialEntry.Status.PENDING,
            FinancialEntry.Status.OVERDUE,
        ),
        date__gte=range_start,
        date__lt=range_end,
    )

    from_proposal = base_qs.filter(related_proposal__isnull=False).aggregate(
        total=Sum("amount"),
    )
    from_proposal_count = base_qs.filter(related_proposal__isnull=False).count()

    # Lead-direto = vem de related_lead E NÃO tem proposta vinculada
    # (entries auto-geradas direto pelo signal `_maybe_generate_finance_entry`)
    from_lead = base_qs.filter(
        related_lead__isnull=False,
        related_proposal__isnull=True,
    ).aggregate(total=Sum("amount"))
    from_lead_count = base_qs.filter(
        related_lead__isnull=False,
        related_proposal__isnull=True,
    ).count()

    # Manuais = sem proposta E sem lead (criados pelo user direto no /finance/)
    manual = base_qs.filter(
        related_proposal__isnull=True,
        related_lead__isnull=True,
    ).aggregate(total=Sum("amount"))
    manual_count = base_qs.filter(
        related_proposal__isnull=True,
        related_lead__isnull=True,
    ).count()

    return {
        "from_proposal": {
            "total": from_proposal.get("total") or Decimal("0"),
            "count": from_proposal_count,
        },
        "from_lead": {
            "total": from_lead.get("total") or Decimal("0"),
            "count": from_lead_count,
        },
        "manual": {
            "total": manual.get("total") or Decimal("0"),
            "count": manual_count,
        },
    }


# ---------------------------------------------------------------------------
# Entry CRUD
# ---------------------------------------------------------------------------


class EntryListView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = FinancialEntry
    template_name = "finance/entry_list.html"
    partial_template_name = "finance/partials/_entry_table.html"
    context_object_name = "entries"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().select_related(
            "category", "bank_account",
            "related_proposal", "related_contract", "related_work_order",
        )
        q = self.request.GET.get("q", "").strip()
        entry_type = self.request.GET.get("type", "").strip()
        status = self.request.GET.get("status", "").strip()
        category = self.request.GET.get("category", "").strip()
        date_from = self.request.GET.get("date_from", "").strip()
        date_to = self.request.GET.get("date_to", "").strip()

        if q:
            qs = qs.filter(Q(description__icontains=q))
        if entry_type:
            qs = qs.filter(type=entry_type)
        if status:
            if status == "overdue":
                qs = qs.filter(
                    status=FinancialEntry.Status.PENDING,
                    date__lt=date.today(),
                )
            else:
                qs = qs.filter(status=status)
        if category:
            qs = qs.filter(category_id=category)
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["type_choices"] = FinancialEntry.Type.choices
        context["status_choices"] = FinancialEntry.Status.choices
        context["categories"] = FinancialCategory.objects.filter(
            empresa=self.request.empresa, is_active=True
        )
        context["current_type"] = self.request.GET.get("type", "")
        context["current_status"] = self.request.GET.get("status", "")
        context["current_category"] = self.request.GET.get("category", "")
        context["current_date_from"] = self.request.GET.get("date_from", "")
        context["current_date_to"] = self.request.GET.get("date_to", "")
        context["current_q"] = self.request.GET.get("q", "")
        return context


class EntryCreateView(EmpresaMixin, HtmxResponseMixin, CreateView):
    model = FinancialEntry
    form_class = FinancialEntryForm
    template_name = "finance/entry_form.html"
    partial_template_name = "finance/partials/_entry_form.html"
    success_url = reverse_lazy("finance:entry_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def form_valid(self, form):
        # RV10 — Se marcado 'parcelar', cria N entries em vez de 1.
        # Cliente pediu: "exemplo serviço 1500 de 3 vezes. gera 3 entradas
        # de 500 nos lançamentos".
        if form.cleaned_data.get("is_installment"):
            entries = form.save_installments(self.request.empresa)
            messages.success(
                self.request,
                f"{len(entries)} parcelas criadas com sucesso "
                f"(de {entries[0].date.strftime('%d/%m/%Y')} a "
                f"{entries[-1].date.strftime('%d/%m/%Y')}).",
            )
            from django.shortcuts import redirect
            return redirect(self.success_url)
        # Caminho padrão: 1 entry. EmpresaMixin.form_valid seta instance.empresa.
        response = super().form_valid(form)
        messages.success(self.request, "Lançamento criado com sucesso.")
        return response


class EntryUpdateView(EmpresaMixin, HtmxResponseMixin, UpdateView):
    model = FinancialEntry
    form_class = FinancialEntryForm
    template_name = "finance/entry_form.html"
    partial_template_name = "finance/partials/_entry_form.html"
    success_url = reverse_lazy("finance:entry_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def form_valid(self, form):
        # RV07 — Permite parcelar um lançamento já existente na edição,
        # dando aos lançamentos automáticos (lead ganho) a mesma opção de
        # parcelamento dos manuais (pedido do PDF, item 1.1). Só divide
        # quando marcado E o lançamento não está pago (preserva o histórico
        # de caixa). O save normal grava o valor total; depois dividimos.
        response = super().form_valid(form)
        if (
            form.cleaned_data.get("is_installment")
            and self.object.status != FinancialEntry.Status.PAID
        ):
            from .services import split_entry_into_installments

            entries = split_entry_into_installments(
                self.object,
                count=form.cleaned_data.get("installment_count") or 2,
                interval_days=form.cleaned_data.get("installment_interval_days") or 30,
            )
            messages.success(
                self.request,
                f"Lançamento dividido em {len(entries)} parcelas "
                f"(de {entries[0].date.strftime('%d/%m/%Y')} a "
                f"{entries[-1].date.strftime('%d/%m/%Y')}).",
            )
        else:
            messages.success(self.request, "Lançamento atualizado com sucesso.")
        return response


class EntryDeleteView(EmpresaMixin, View):
    """RV10 — Exclui lançamento financeiro (hard delete).

    Cliente reportou: "não tem como excluir lançamento pendente". A coluna
    Ações só tinha 'editar' e 'marcar como pago'. Sem essa view, o user só
    conseguia excluir via Django admin.

    Comportamento:
    - Hard delete (FinancialEntry não tem soft-delete no model).
    - Aceita qualquer status (pending/paid/overdue/cancelled).
    - Se auto-gerada vinculada a Lead em won_stage: o backfill on-demand
      vai SUGERIR recriar quando o user clicar "Sincronizar agora" — mas
      o signal post_save do Lead NÃO recria automaticamente (idempotência
      do generate_entry_from_lead_won verifica por `related_lead=lead +
      auto_generated=True`, então uma vez deletada, ele só recria se o
      lead for salvo de novo). Por isso adicionamos warning específico
      na mensagem.
    - HTMX-friendly: se vier de HTMX, retorna 204 (linha some via swap).
    """

    def post(self, request, pk):
        entry = get_object_or_404(
            FinancialEntry, pk=pk, empresa=request.empresa
        )
        # Snapshot pra mensagem amigável
        description = entry.description
        amount = entry.amount
        was_auto = entry.auto_generated
        had_lead = entry.related_lead_id is not None
        had_proposal = entry.related_proposal_id is not None

        entry.delete()

        msg_parts = [f"Lançamento '{description}' (R$ {amount}) excluído."]
        if was_auto and had_lead:
            msg_parts.append(
                "⚠ Era auto-gerado pelo lead. Qualquer edição/save do lead "
                "enquanto ele estiver em etapa de ganho recriará o lançamento."
            )
        elif was_auto and had_proposal:
            msg_parts.append(
                "⚠ Era auto-gerado pela proposta. Se a proposta for aceita "
                "novamente (após reabertura), um novo lançamento será criado."
            )
        messages.success(request, " ".join(msg_parts))

        if request.htmx:
            # 204 No Content + HX-Trigger pra atualizar contadores se quiser
            response = HttpResponse(status=204)
            response["HX-Trigger"] = "entryDeleted"
            return response

        from django.shortcuts import redirect
        referer = request.META.get("HTTP_REFERER", "")
        if "entries" in referer:
            return redirect("finance:entry_list")
        return redirect("finance:finance_overview")


class BackfillWonLeadEntriesView(EmpresaMixin, View):
    """RV10 — POST que regenera FinancialEntry para leads em won_stage sem entry.

    Cliente reportou: "fechei 3 leads sem proposta mas não aparecem na
    previsão". Causa: signal RV06 só dispara em saves após o deploy; leads
    movidos antes (ou por script) ficaram sem entry. Este endpoint faz
    backfill on-demand a partir do dashboard.
    """

    def post(self, request):
        from .services import backfill_won_lead_entries
        result = backfill_won_lead_entries(request.empresa)
        scanned = result["scanned"]
        created = len(result["created"])
        skipped = result["skipped"]
        if scanned == 0:
            messages.info(
                request, "Nenhum lead aguardando lançamento — tudo certo!",
            )
        else:
            msg = (
                f"Sincronização concluída: {created} lançamento"
                f"{'s' if created != 1 else ''} criado"
                f"{'s' if created != 1 else ''} a partir de {scanned} "
                f"lead{'s' if scanned != 1 else ''} ganho"
                f"{'s' if scanned != 1 else ''}."
            )
            if skipped:
                msg += (
                    f" ({skipped} pulado{'s' if skipped != 1 else ''} — "
                    f"já tinham proposta com lançamento.)"
                )
            messages.success(request, msg)
        from django.shortcuts import redirect
        return redirect("finance:finance_overview")


class ResyncZeroValuesView(EmpresaMixin, View):
    """RV07 — POST que re-puxa o valor de lançamentos auto-gerados zerados.

    Cliente reportou: "na geração automática não está puxando o valor que tá
    no lead". Causa: lançamentos criados ANTES da correção 1.1 (ou com o valor
    apenas na Oportunidade) ficaram em R$ 0,00 e a correção não reescreve o
    passado. Este botão resolve on-demand (estimated_value → Oportunidade →
    serviço). Idempotente.
    """

    def post(self, request):
        from django.shortcuts import redirect

        from .services import resync_zero_value_entries
        result = resync_zero_value_entries(request.empresa)
        n = len(result["updated"])
        if n:
            messages.success(
                request,
                f"{n} lançamento{'s' if n != 1 else ''} atualizado"
                f"{'s' if n != 1 else ''} com o valor do negócio (puxado do "
                f"lead/oportunidade/serviço).",
            )
        else:
            messages.info(
                request,
                "Nenhum lançamento zerado com valor a puxar — os que seguem em "
                "R$ 0,00 não têm valor no lead/oportunidade/serviço. Ajuste-os "
                "manualmente em 'Ver e ajustar'.",
            )
        return redirect("finance:finance_overview")


class EntryMarkPaidView(EmpresaMixin, View):
    """Marca um lançamento como pago."""

    def post(self, request, pk):
        entry = get_object_or_404(
            FinancialEntry, pk=pk, empresa=request.empresa
        )
        entry.status = FinancialEntry.Status.PAID
        entry.paid_date = timezone.now().date()
        entry.save(update_fields=["status", "paid_date", "updated_at"])

        if request.htmx:
            html = render_to_string(
                "finance/partials/_entry_row.html",
                {"entry": entry},
                request=request,
            )
            return HttpResponse(html)

        messages.success(request, "Lançamento marcado como pago.")
        from django.shortcuts import redirect

        referer = request.META.get("HTTP_REFERER", "")
        if "entries" in referer:
            return redirect("finance:entry_list")
        return redirect("finance:finance_overview")


# ---------------------------------------------------------------------------
# Category Views (settings)
# ---------------------------------------------------------------------------


class CategoryListView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = FinancialCategory
    template_name = "finance/category_list.html"
    partial_template_name = "finance/partials/_category_table.html"
    context_object_name = "categories"
    paginate_by = 25


# ---------------------------------------------------------------------------
# RV08 (6.1) — Open Finance: conectar/importar + inbox de classificação
# ---------------------------------------------------------------------------


class OpenFinanceView(EmpresaMixin, TemplateView):
    """Tela do Open Finance: conexão, importação e classificação."""

    template_name = "finance/open_finance.html"

    def get_context_data(self, **kwargs):
        from apps.crm.models import Lead
        from apps.operations.models import WorkOrder

        context = super().get_context_data(**kwargs)
        empresa = self.request.empresa
        context["connection"] = (
            BankConnection.objects.filter(empresa=empresa).order_by("-created_at").first()
        )
        context["pending"] = (
            ImportedTransaction.objects.filter(
                empresa=empresa,
                classification_status=ImportedTransaction.Status.PENDING,
            )
            .select_related("bank_account")
            .order_by("-date", "-id")
        )
        context["recent_classified"] = (
            ImportedTransaction.objects.filter(
                empresa=empresa,
                classification_status=ImportedTransaction.Status.CLASSIFIED,
            )
            .select_related("classified_entry")
            .order_by("-updated_at")[:10]
        )
        context["categories"] = FinancialCategory.objects.filter(
            empresa=empresa, is_active=True,
        ).order_by("type", "name")
        context["work_orders"] = WorkOrder.objects.filter(empresa=empresa).order_by(
            "-created_at",
        )[:200]
        context["leads"] = Lead.objects.filter(empresa=empresa).order_by("name")[:200]
        return context


class OpenFinanceConnectSandboxView(EmpresaMixin, View):
    """Conecta o provider de demonstração e importa movimentações fictícias."""

    http_method_names = ["post"]

    def post(self, request):
        from .open_finance import get_provider, import_transactions

        empresa = request.empresa
        provider = get_provider("sandbox")
        if provider is None:
            messages.error(request, "Provedor de demonstração indisponível.")
            return redirect("finance:open_finance")
        conn, _created = BankConnection.objects.get_or_create(
            empresa=empresa,
            provider=BankConnection.Provider.SANDBOX,
            defaults={"status": BankConnection.Status.CONNECTED},
        )
        rows = provider.fetch_transactions()
        res = import_transactions(empresa, rows, connection=conn)
        messages.success(
            request,
            f"Banco de demonstração conectado. {res['created']} movimentação(ões) "
            f"importada(s) ({res['skipped']} já existia(m)).",
        )
        return redirect("finance:open_finance")


class OpenFinanceImportView(EmpresaMixin, View):
    """Importa um extrato CSV/OFX enviado pelo usuário."""

    http_method_names = ["post"]
    MAX_BYTES = 5 * 1024 * 1024  # 5 MB

    def post(self, request):
        from .open_finance import import_transactions, parse_statement

        empresa = request.empresa
        upload = request.FILES.get("file")
        if not upload:
            messages.error(request, "Selecione um arquivo CSV ou OFX.")
            return redirect("finance:open_finance")
        if upload.size > self.MAX_BYTES:
            messages.error(request, "Arquivo muito grande (máx. 5 MB).")
            return redirect("finance:open_finance")

        try:
            rows = parse_statement(upload.name, upload.read())
        except Exception:  # noqa: BLE001
            messages.error(
                request,
                "Não foi possível ler o arquivo. Confira se é um CSV/OFX válido.",
            )
            return redirect("finance:open_finance")

        if not rows:
            messages.warning(
                request,
                "Nenhuma movimentação reconhecida no arquivo. Para CSV use as "
                "colunas: data, descrição, valor.",
            )
            return redirect("finance:open_finance")

        conn, _created = BankConnection.objects.get_or_create(
            empresa=empresa,
            provider=BankConnection.Provider.MANUAL,
            defaults={"status": BankConnection.Status.CONNECTED},
        )
        res = import_transactions(empresa, rows, connection=conn)
        messages.success(
            request,
            f"Extrato importado: {res['created']} nova(s) movimentação(ões) "
            f"({res['skipped']} já existia(m)).",
        )
        return redirect("finance:open_finance")


class OpenFinanceClassifyView(EmpresaMixin, View):
    """Classifica uma movimentação, gerando um lançamento financeiro."""

    http_method_names = ["post"]

    def post(self, request, pk):
        from apps.crm.models import Lead
        from apps.operations.models import WorkOrder

        from .open_finance import classify_transaction

        empresa = request.empresa
        txn = get_object_or_404(
            ImportedTransaction, pk=pk, empresa=empresa,
            classification_status=ImportedTransaction.Status.PENDING,
        )
        entry_type = request.POST.get("type") or txn.suggested_type
        if entry_type not in (FinancialEntry.Type.INCOME, FinancialEntry.Type.EXPENSE):
            entry_type = txn.suggested_type

        category = None
        category_id = request.POST.get("category")
        if category_id:
            category = FinancialCategory.objects.filter(
                pk=category_id, empresa=empresa,
            ).first()

        work_order = None
        wo_id = request.POST.get("work_order")
        if wo_id:
            work_order = WorkOrder.objects.filter(pk=wo_id, empresa=empresa).first()

        lead = None
        lead_id = request.POST.get("lead")
        if lead_id:
            lead = Lead.objects.filter(pk=lead_id, empresa=empresa).first()
        if lead is None and work_order is not None:
            lead = work_order.lead

        classify_transaction(
            txn, entry_type=entry_type, category=category,
            related_work_order=work_order, related_lead=lead,
        )
        messages.success(request, "Movimentação classificada e lançada no financeiro.")
        return redirect("finance:open_finance")


class OpenFinanceIgnoreView(EmpresaMixin, View):
    """Marca uma movimentação como ignorada (não vira lançamento)."""

    http_method_names = ["post"]

    def post(self, request, pk):
        txn = get_object_or_404(
            ImportedTransaction, pk=pk, empresa=request.empresa,
            classification_status=ImportedTransaction.Status.PENDING,
        )
        txn.classification_status = ImportedTransaction.Status.IGNORED
        txn.save(update_fields=["classification_status", "updated_at"])
        messages.success(request, "Movimentação ignorada.")
        return redirect("finance:open_finance")
