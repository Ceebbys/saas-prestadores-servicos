from datetime import date

from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.views.generic import TemplateView

from apps.core.mixins import EmpresaMixin


class DashboardView(EmpresaMixin, TemplateView):
    template_name = "dashboard/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        empresa = self.request.empresa

        today = timezone.now().date()
        month_start = today.replace(day=1)

        # Import models
        from apps.crm.models import Lead, Pipeline
        from apps.finance.models import FinancialEntry
        from apps.operations.models import WorkOrder
        from apps.proposals.models import Proposal

        # Lead stats
        leads = Lead.objects.filter(empresa=empresa)
        context["total_leads"] = leads.count()
        context["new_leads_month"] = leads.filter(created_at__date__gte=month_start).count()

        # Proposal stats
        proposals = Proposal.objects.filter(empresa=empresa)
        context["proposals_open"] = proposals.filter(
            status__in=["draft", "sent", "viewed"]
        ).count()
        context["proposals_accepted"] = proposals.filter(status="accepted").count()
        context["proposals_value"] = proposals.filter(status="accepted").aggregate(
            total=Sum("total")
        )["total"] or 0

        # Work order stats
        work_orders = WorkOrder.objects.filter(empresa=empresa)
        context["wo_pending"] = work_orders.filter(
            status__in=["pending", "scheduled"]
        ).count()
        context["wo_in_progress"] = work_orders.filter(status="in_progress").count()

        # Finance stats
        entries = FinancialEntry.objects.filter(empresa=empresa, date__gte=month_start)
        context["income_month"] = entries.filter(
            type="income", status="paid"
        ).aggregate(total=Sum("amount"))["total"] or 0
        context["expense_month"] = entries.filter(
            type="expense", status="paid"
        ).aggregate(total=Sum("amount"))["total"] or 0
        context["balance_month"] = context["income_month"] - context["expense_month"]
        context["overdue_count"] = FinancialEntry.objects.filter(
            empresa=empresa, status="pending", date__lt=today
        ).count()

        # Recent leads
        context["recent_leads"] = leads.order_by("-created_at")[:5]

        # Upcoming work orders
        context["upcoming_orders"] = work_orders.filter(
            scheduled_date__gte=today,
            status__in=["pending", "scheduled"],
        ).order_by("scheduled_date")[:5]

        # Pipeline summary
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

        return context
