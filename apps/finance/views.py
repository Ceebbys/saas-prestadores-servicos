from datetime import date

from django.contrib import messages
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
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
from .models import BankAccount, FinancialCategory, FinancialEntry


# ---------------------------------------------------------------------------
# Finance Overview
# ---------------------------------------------------------------------------


class FinanceOverviewView(EmpresaMixin, HtmxResponseMixin, TemplateView):
    template_name = "finance/overview.html"
    partial_template_name = "finance/partials/_overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = date.today()
        empresa = self.request.empresa

        month_entries = FinancialEntry.objects.filter(
            empresa=empresa,
            date__year=today.year,
            date__month=today.month,
        )

        # RV10 — Cliente reportou "fiz 3 despesas mas só conta 2". A SOMA
        # estava correta, mas a lista de "Recentes" mostra só top-10 — o
        # 3º lançamento estava fora. Agora mostramos contagem + breakdown
        # PAGO/PENDENTE no card pra reduzir a confusão.
        from django.db.models import Count

        income_paid = month_entries.filter(
            type=FinancialEntry.Type.INCOME,
            status=FinancialEntry.Status.PAID,
        ).aggregate(total=Sum("amount"), count=Count("id"))
        total_income = income_paid.get("total") or 0
        income_paid_count = income_paid.get("count") or 0

        income_pending = month_entries.filter(
            type=FinancialEntry.Type.INCOME,
            status=FinancialEntry.Status.PENDING,
        ).aggregate(total=Sum("amount"), count=Count("id"))
        income_pending_total = income_pending.get("total") or 0
        income_pending_count = income_pending.get("count") or 0

        expense_paid = month_entries.filter(
            type=FinancialEntry.Type.EXPENSE,
            status=FinancialEntry.Status.PAID,
        ).aggregate(total=Sum("amount"), count=Count("id"))
        total_expense = expense_paid.get("total") or 0
        expense_paid_count = expense_paid.get("count") or 0

        expense_pending = month_entries.filter(
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
                "bank_accounts": bank_accounts,
                "forecast_months": forecast["months"],
                "forecast_total": forecast["total"],
                "forecast_max": forecast["max"],
                "forecast_breakdown": forecast_breakdown,
                "won_leads_pending": won_leads_pending,
                "won_leads_pending_preview": won_leads_pending_preview,
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
        response = super().form_valid(form)
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
                "⚠ Era auto-gerado pelo lead. Se mover o lead novamente "
                "para etapa de ganho, um novo lançamento será criado."
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
