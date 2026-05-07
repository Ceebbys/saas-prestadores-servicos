import calendar as cal_module
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import (
    Avg,
    Count,
    DateTimeField,
    DurationField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
)
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone
from django.views.generic import TemplateView

from apps.core.mixins import EmpresaMixin, HtmxResponseMixin

MONTH_NAMES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


class DashboardView(EmpresaMixin, HtmxResponseMixin, TemplateView):
    template_name = "dashboard/index.html"
    partial_template_name = "dashboard/partials/_dashboard_content.html"

    def _get_period(self):
        """Parse period filters from GET params."""
        today = timezone.now().date()
        period = self.request.GET.get("period", "month")

        if period == "year":
            year = int(self.request.GET.get("year", today.year))
            return date(year, 1, 1), date(year, 12, 31), f"Ano {year}"

        if period == "custom":
            try:
                date_from = date.fromisoformat(self.request.GET.get("date_from", ""))
                date_to = date.fromisoformat(self.request.GET.get("date_to", ""))
                label = f"{date_from.strftime('%d/%m/%Y')} — {date_to.strftime('%d/%m/%Y')}"
                return date_from, date_to, label
            except (ValueError, TypeError):
                pass

        # Default: month
        year = int(self.request.GET.get("year", today.year))
        month = int(self.request.GET.get("month", today.month))
        month_start = date(year, month, 1)
        last_day = cal_module.monthrange(year, month)[1]
        month_end = date(year, month, last_day)
        label = f"{MONTH_NAMES_PT[month]} {year}"
        return month_start, month_end, label

    def _parse_decimal(self, raw):
        """Safely parse a decimal from GET param."""
        if not raw:
            return None
        try:
            return Decimal(raw)
        except (InvalidOperation, ValueError, TypeError):
            return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        empresa = self.request.empresa
        today = timezone.now().date()
        period_start, period_end, period_label = self._get_period()

        # --- Parse all filter params ---
        service_type_id = self.request.GET.get("service_type")
        status_filter = self.request.GET.get("status")
        lead_source = self.request.GET.get("lead_source")
        payment_method = self.request.GET.get("payment_method")
        is_installment = self.request.GET.get("is_installment")
        value_min = self._parse_decimal(self.request.GET.get("value_min"))
        value_max = self._parse_decimal(self.request.GET.get("value_max"))

        # Import models
        from apps.crm.models import Lead, LeadContact, Opportunity, Pipeline
        from apps.finance.models import FinancialEntry
        from apps.operations.models import ServiceType, WorkOrder
        from apps.proposals.models import Proposal

        # --- Filter context (preserve selections in template) ---
        context["period"] = self.request.GET.get("period", "month")
        context["period_label"] = period_label
        context["filter_year"] = self.request.GET.get("year", str(today.year))
        context["filter_month"] = self.request.GET.get("month", str(today.month))
        context["filter_date_from"] = self.request.GET.get("date_from", "")
        context["filter_date_to"] = self.request.GET.get("date_to", "")
        context["filter_service_type"] = service_type_id or ""
        context["filter_status"] = status_filter or ""
        context["filter_lead_source"] = lead_source or ""
        context["filter_payment_method"] = payment_method or ""
        context["filter_is_installment"] = is_installment or ""
        context["filter_value_min"] = self.request.GET.get("value_min", "")
        context["filter_value_max"] = self.request.GET.get("value_max", "")

        # Dropdown choices
        context["service_types"] = ServiceType.objects.filter(
            empresa=empresa, is_active=True
        )
        context["month_choices"] = [
            (str(m), MONTH_NAMES_PT[m]) for m in range(1, 13)
        ]
        context["year_choices"] = list(range(today.year - 2, today.year + 1))
        context["lead_source_choices"] = Lead.Source.choices
        context["payment_method_choices"] = Proposal.PaymentMethod.choices
        context["wo_status_choices"] = WorkOrder.Status.choices

        # Check if any advanced filter is active (for "Mais filtros" toggle)
        context["has_advanced_filters"] = any([
            lead_source, payment_method, is_installment,
            value_min is not None, value_max is not None,
        ])

        # ===== LEAD STATS =====
        leads = Lead.objects.filter(empresa=empresa)
        if lead_source:
            leads = leads.filter(source=lead_source)

        context["total_leads"] = leads.count()
        context["new_leads_period"] = leads.filter(
            created_at__date__gte=period_start,
            created_at__date__lte=period_end,
        ).count()

        # Leads by source (for chart)
        context["leads_by_source"] = list(
            leads.values("source")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        # ===== PROPOSAL STATS =====
        proposals = Proposal.objects.filter(empresa=empresa)
        if payment_method:
            proposals = proposals.filter(payment_method=payment_method)
        if is_installment == "1":
            proposals = proposals.filter(is_installment=True)
        if value_min is not None:
            proposals = proposals.filter(total__gte=value_min)
        if value_max is not None:
            proposals = proposals.filter(total__lte=value_max)

        context["proposals_open"] = proposals.filter(
            status__in=["draft", "sent", "viewed"]
        ).count()
        proposals_accepted = proposals.filter(status="accepted")
        context["proposals_accepted"] = proposals_accepted.count()
        context["proposals_value"] = proposals_accepted.aggregate(
            total=Sum("total")
        )["total"] or 0

        # Conversion rate (period-scoped by creation date)
        proposals_in_period = proposals.filter(
            created_at__date__gte=period_start,
            created_at__date__lte=period_end,
        )
        total_proposals_period = proposals_in_period.count()
        accepted_proposals_period = proposals_in_period.filter(
            status="accepted"
        ).count()
        context["total_proposals_period"] = total_proposals_period
        context["accepted_proposals_period"] = accepted_proposals_period
        context["conversion_rate"] = (
            round(accepted_proposals_period / total_proposals_period * 100, 1)
            if total_proposals_period > 0 else 0
        )

        # Average proposal value
        context["avg_proposal_value"] = (
            proposals_accepted.aggregate(avg=Avg("total"))["avg"] or 0
        )

        # ===== WORK ORDER STATS =====
        work_orders = WorkOrder.objects.filter(empresa=empresa)
        if service_type_id:
            work_orders = work_orders.filter(service_type_id=service_type_id)
        if status_filter:
            work_orders = work_orders.filter(status=status_filter)

        context["wo_pending"] = work_orders.filter(
            status__in=["pending", "scheduled"]
        ).count()
        context["wo_in_progress"] = work_orders.filter(status="in_progress").count()

        # ===== FINANCE STATS =====
        entries = FinancialEntry.objects.filter(
            empresa=empresa,
            date__gte=period_start,
            date__lte=period_end,
        )
        if service_type_id:
            entries = entries.filter(
                Q(related_work_order__service_type_id=service_type_id)
                | Q(related_work_order__isnull=True)
            )
        if payment_method:
            entries = entries.filter(
                Q(related_proposal__payment_method=payment_method)
                | Q(related_proposal__isnull=True)
            )
        if value_min is not None:
            entries = entries.filter(amount__gte=value_min)
        if value_max is not None:
            entries = entries.filter(amount__lte=value_max)

        context["income_period"] = entries.filter(
            type="income", status="paid"
        ).aggregate(total=Sum("amount"))["total"] or 0
        context["expense_period"] = entries.filter(
            type="expense", status="paid"
        ).aggregate(total=Sum("amount"))["total"] or 0
        context["balance_period"] = context["income_period"] - context["expense_period"]
        context["overdue_count"] = FinancialEntry.objects.filter(
            empresa=empresa, status="pending", date__lt=today
        ).count()

        # Revenue by service type (top 5)
        context["revenue_by_service"] = list(
            FinancialEntry.objects.filter(
                empresa=empresa,
                type="income",
                status="paid",
                date__gte=period_start,
                date__lte=period_end,
                related_work_order__isnull=False,
            )
            .values("related_work_order__service_type__name")
            .annotate(total=Sum("amount"))
            .order_by("-total")[:5]
        )

        # ===== LISTS =====
        context["recent_leads"] = (
            leads.select_related("contato", "pipeline_stage")
            .order_by("-created_at")[:5]
        )

        # Upcoming work orders (always show upcoming, not filtered)
        context["upcoming_orders"] = (
            WorkOrder.objects.filter(
                empresa=empresa,
                scheduled_date__gte=today,
                status__in=["pending", "scheduled"],
            ).order_by("scheduled_date")[:5]
        )

        # ===== PIPELINE SUMMARY =====
        try:
            pipeline = Pipeline.objects.filter(empresa=empresa, is_default=True).first()
            if pipeline:
                stages = (
                    pipeline.stages.annotate(
                        opp_count=Count("opportunities"),
                        opp_value=Sum("opportunities__value"),
                    )
                    .exclude(is_lost=True)
                    .order_by("order")
                )
                context["pipeline_stages"] = stages
                context["total_opportunities"] = sum(
                    s.opp_count for s in stages
                )
        except Exception:
            pass

        # Recent accepted proposals
        context["recent_accepted_proposals"] = (
            proposals.filter(status="accepted")
            .select_related("lead")
            .order_by("-updated_at")[:5]
        )

        # ===== NEW STRATEGIC KPIs =====

        # 1. Avg lead closure days (Opportunity won/lost in period).
        # Safety filter closed_at >= lead.created_at to avoid negative durations
        # from clock skew or backfilled data.
        closed_opps = Opportunity.objects.filter(empresa=empresa).filter(
            Q(
                current_stage__is_won=True,
                won_at__date__gte=period_start,
                won_at__date__lte=period_end,
                won_at__gte=F("lead__created_at"),
            )
            | Q(
                current_stage__is_lost=True,
                lost_at__date__gte=period_start,
                lost_at__date__lte=period_end,
                lost_at__gte=F("lead__created_at"),
            )
        ).annotate(
            closed_at=Coalesce("won_at", "lost_at"),
        ).annotate(
            closure=ExpressionWrapper(
                F("closed_at") - F("lead__created_at"),
                output_field=DurationField(),
            )
        ).aggregate(avg=Avg("closure"))
        closure_avg = closed_opps["avg"]
        context["avg_lead_closure_days"] = (
            max(closure_avg.days, 0) if closure_avg else 0
        )

        # 2. Follow-up rate (% of leads created in period with >= 1 contact)
        leads_in_period = Lead.objects.filter(
            empresa=empresa,
            created_at__date__gte=period_start,
            created_at__date__lte=period_end,
        )
        total_leads_period = leads_in_period.count()
        contacted_leads = (
            leads_in_period.filter(contacts__isnull=False).distinct().count()
        )
        context["followup_rate"] = (
            round(contacted_leads / total_leads_period * 100, 1)
            if total_leads_period else 0
        )
        context["followup_contacted"] = contacted_leads
        context["followup_total"] = total_leads_period

        # 3. Overdue rate % (monetary — pending receivables past due)
        receivables_qs = FinancialEntry.objects.filter(
            empresa=empresa,
            type="income",
            date__gte=period_start,
            date__lte=period_end,
        ).exclude(status="cancelled")
        total_receivable = receivables_qs.aggregate(t=Sum("amount"))["t"] or Decimal("0")
        overdue_amount = receivables_qs.filter(
            status__in=["pending", "overdue"], date__lt=today,
        ).aggregate(t=Sum("amount"))["t"] or Decimal("0")
        context["overdue_rate_pct"] = (
            round(float(overdue_amount / total_receivable * 100), 1)
            if total_receivable else 0
        )
        context["overdue_amount"] = overdue_amount

        # 4. Avg work-order execution days (completed in period).
        # Safety filter completed_at >= scheduled_date to avoid negative durations.
        completed_wo = WorkOrder.objects.filter(
            empresa=empresa,
            status="completed",
            completed_at__isnull=False,
            scheduled_date__isnull=False,
            completed_at__date__gte=period_start,
            completed_at__date__lte=period_end,
        ).filter(
            completed_at__date__gte=F("scheduled_date"),
        ).annotate(
            start_dt=Cast("scheduled_date", output_field=DateTimeField()),
        ).annotate(
            exec_time=ExpressionWrapper(
                F("completed_at") - F("start_dt"),
                output_field=DurationField(),
            )
        ).aggregate(avg=Avg("exec_time"))
        wo_avg = completed_wo["avg"]
        context["avg_wo_execution_days"] = (
            max(wo_avg.days, 0) if wo_avg else 0
        )

        return context
