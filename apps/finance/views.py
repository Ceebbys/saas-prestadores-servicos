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
            }
        )
        return context


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
