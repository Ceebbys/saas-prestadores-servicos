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

        total_income = (
            month_entries.filter(type=FinancialEntry.Type.INCOME, status=FinancialEntry.Status.PAID)
            .aggregate(total=Sum("amount"))["total"]
        ) or 0

        total_expense = (
            month_entries.filter(type=FinancialEntry.Type.EXPENSE, status=FinancialEntry.Status.PAID)
            .aggregate(total=Sum("amount"))["total"]
        ) or 0

        balance = total_income - total_expense

        pending_count = month_entries.filter(
            status=FinancialEntry.Status.PENDING
        ).count()

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
                "total_expense": total_expense,
                "balance": balance,
                "pending_count": pending_count,
                "overdue_count": overdue_count,
                "recent_entries": recent_entries,
                "current_month": today,
                "bank_accounts": bank_accounts,
                "forecast_months": forecast["months"],
                "forecast_total": forecast["total"],
                "forecast_max": forecast["max"],
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
