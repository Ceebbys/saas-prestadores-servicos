import calendar as cal_module
from datetime import date

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from apps.core.mixins import EmpresaMixin, HtmxResponseMixin

from .forms import ServiceTypeForm, WorkOrderForm
from .models import ServiceType, Team, WorkOrder, WorkOrderChecklist


# ---------------------------------------------------------------------------
# WorkOrder Views
# ---------------------------------------------------------------------------


class WorkOrderListView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = WorkOrder
    template_name = "operations/work_order_list.html"
    partial_template_name = "operations/partials/_work_order_table.html"
    context_object_name = "work_orders"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related(
            "lead", "service_type", "assigned_to", "assigned_team"
        )
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        priority = self.request.GET.get("priority", "").strip()
        assigned_to = self.request.GET.get("assigned_to", "").strip()
        team = self.request.GET.get("team", "").strip()

        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(number__icontains=q))
        if status:
            qs = qs.filter(status=status)
        if priority:
            qs = qs.filter(priority=priority)
        if assigned_to:
            qs = qs.filter(assigned_to_id=assigned_to)
        if team:
            qs = qs.filter(assigned_team_id=team)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = WorkOrder.Status.choices
        context["priority_choices"] = WorkOrder.Priority.choices
        context["teams"] = Team.objects.filter(
            empresa=self.request.empresa, is_active=True
        )
        context["current_status"] = self.request.GET.get("status", "")
        context["current_priority"] = self.request.GET.get("priority", "")
        context["current_assigned_to"] = self.request.GET.get("assigned_to", "")
        context["current_team"] = self.request.GET.get("team", "")
        context["current_q"] = self.request.GET.get("q", "")
        return context


class WorkOrderDetailView(EmpresaMixin, DetailView):
    model = WorkOrder
    template_name = "operations/work_order_detail.html"
    context_object_name = "work_order"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("lead", "proposal", "contract", "service_type", "assigned_to", "assigned_team")
            .prefetch_related("checklist_items")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        items = self.object.checklist_items.all()
        total = len(items)
        completed = sum(1 for i in items if i.is_completed)
        context["checklist_total"] = total
        context["checklist_completed"] = completed
        context["checklist_pct"] = int((completed / total) * 100) if total else 0
        return context


class WorkOrderCreateView(EmpresaMixin, HtmxResponseMixin, CreateView):
    model = WorkOrder
    form_class = WorkOrderForm
    template_name = "operations/work_order_form.html"
    partial_template_name = "operations/partials/_work_order_form.html"
    success_url = reverse_lazy("operations:work_order_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        from_proposal = self.request.GET.get("from_proposal")
        from_contract = self.request.GET.get("from_contract")

        if from_proposal:
            try:
                from apps.proposals.models import Proposal

                proposal = Proposal.objects.get(
                    pk=from_proposal, empresa=self.request.empresa
                )
                initial["proposal"] = proposal.pk
                initial["lead"] = proposal.lead_id
                initial["title"] = proposal.title
            except Proposal.DoesNotExist:
                pass

        if from_contract:
            try:
                from apps.contracts.models import Contract

                contract = Contract.objects.get(
                    pk=from_contract, empresa=self.request.empresa
                )
                initial["contract"] = contract.pk
                initial["title"] = getattr(contract, "title", "")
            except (Contract.DoesNotExist, ImportError, LookupError):
                pass

        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Ordem de serviço criada com sucesso.")
        return response


class WorkOrderUpdateView(EmpresaMixin, HtmxResponseMixin, UpdateView):
    model = WorkOrder
    form_class = WorkOrderForm
    template_name = "operations/work_order_form.html"
    partial_template_name = "operations/partials/_work_order_form.html"
    success_url = reverse_lazy("operations:work_order_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Ordem de serviço atualizada com sucesso.")
        return response


class WorkOrderDeleteView(EmpresaMixin, DeleteView):
    model = WorkOrder
    success_url = reverse_lazy("operations:work_order_list")
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        messages.success(request, "Ordem de serviço excluída com sucesso.")
        return self.delete(request, *args, **kwargs)


class WorkOrderStatusView(EmpresaMixin, View):
    """Altera o status da ordem de serviço."""

    def post(self, request, pk):
        work_order = get_object_or_404(
            WorkOrder, pk=pk, empresa=request.empresa
        )
        new_status = request.POST.get("status")
        now = timezone.now()

        valid_transitions = {
            WorkOrder.Status.PENDING: [
                WorkOrder.Status.SCHEDULED,
                WorkOrder.Status.IN_PROGRESS,
                WorkOrder.Status.CANCELLED,
            ],
            WorkOrder.Status.SCHEDULED: [
                WorkOrder.Status.IN_PROGRESS,
                WorkOrder.Status.CANCELLED,
            ],
            WorkOrder.Status.IN_PROGRESS: [
                WorkOrder.Status.ON_HOLD,
                WorkOrder.Status.COMPLETED,
                WorkOrder.Status.CANCELLED,
            ],
            WorkOrder.Status.ON_HOLD: [
                WorkOrder.Status.IN_PROGRESS,
                WorkOrder.Status.CANCELLED,
            ],
        }

        allowed = valid_transitions.get(work_order.status, [])
        if new_status in allowed:
            work_order.status = new_status
            if new_status == WorkOrder.Status.COMPLETED:
                work_order.completed_at = now
            work_order.save()
            messages.success(request, "Status da OS atualizado.")
        else:
            messages.error(request, "Transição de status inválida.")

        from django.shortcuts import redirect

        return redirect("operations:work_order_detail", pk=work_order.pk)


class WorkOrderChecklistToggleView(EmpresaMixin, View):
    """Alterna o estado de conclusão de um item de checklist da OS."""

    def post(self, request, wo_pk, item_pk):
        work_order = get_object_or_404(
            WorkOrder, pk=wo_pk, empresa=request.empresa
        )
        item = get_object_or_404(
            WorkOrderChecklist, pk=item_pk, work_order=work_order
        )

        if item.is_completed:
            item.is_completed = False
            item.completed_at = None
        else:
            item.is_completed = True
            item.completed_at = timezone.now()
        item.save()

        if request.htmx:
            html = render_to_string(
                "operations/partials/_checklist_item.html",
                {"item": item, "work_order": work_order},
                request=request,
            )
            return HttpResponse(html)

        return HttpResponse(status=204)


# ---------------------------------------------------------------------------
# PDF Export
# ---------------------------------------------------------------------------


class WorkOrderPDFView(EmpresaMixin, DetailView):
    """Gera PDF profissional da Ordem de Serviço via WeasyPrint."""

    model = WorkOrder

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("lead", "proposal", "contract", "service_type", "assigned_to")
            .prefetch_related("checklist_items")
        )

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        wo = self.object
        items = list(wo.checklist_items.all())
        total = len(items)
        completed = sum(1 for i in items if i.is_completed)

        html_string = render_to_string(
            "operations/work_order_pdf.html",
            {
                "work_order": wo,
                "empresa": request.empresa,
                "checklist_items": items,
                "checklist_total": total,
                "checklist_completed": completed,
                "now": timezone.now(),
            },
            request=request,
        )

        import weasyprint

        pdf = weasyprint.HTML(string=html_string).write_pdf()

        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="OS-{wo.number}.pdf"'
        )
        return response


# ---------------------------------------------------------------------------
# Calendar View
# ---------------------------------------------------------------------------


class CalendarView(EmpresaMixin, HtmxResponseMixin, TemplateView):
    template_name = "operations/calendar.html"
    partial_template_name = "operations/partials/_calendar.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = date.today()

        try:
            year = int(self.request.GET.get("year", today.year))
            month = int(self.request.GET.get("month", today.month))
        except (ValueError, TypeError):
            year, month = today.year, today.month

        # Clamp values
        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1

        MONTH_NAMES_PT = {
            1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
            5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
            9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
        }

        cal = cal_module.Calendar(firstweekday=6)  # Sunday first
        month_days = cal.monthdayscalendar(year, month)

        # Get work orders for this month
        work_orders = WorkOrder.objects.filter(
            empresa=self.request.empresa,
            scheduled_date__year=year,
            scheduled_date__month=month,
        ).select_related("assigned_to", "assigned_team", "service_type")

        # Apply filters
        filter_team = self.request.GET.get("team", "").strip()
        filter_assigned = self.request.GET.get("assigned_to", "").strip()
        if filter_team:
            work_orders = work_orders.filter(assigned_team_id=filter_team)
        if filter_assigned:
            work_orders = work_orders.filter(assigned_to_id=filter_assigned)

        # Group by day
        wo_by_day = {}
        for wo in work_orders:
            day = wo.scheduled_date.day
            wo_by_day.setdefault(day, []).append(wo)

        # Teams and members for filters
        teams = Team.objects.filter(
            empresa=self.request.empresa, is_active=True
        )
        from apps.accounts.models import Membership

        member_ids = Membership.objects.filter(
            empresa=self.request.empresa, is_active=True
        ).values_list("user_id", flat=True)
        from apps.accounts.models import User

        members = User.objects.filter(id__in=member_ids)

        # Previous / next month
        if month == 1:
            prev_month, prev_year = 12, year - 1
        else:
            prev_month, prev_year = month - 1, year

        if month == 12:
            next_month, next_year = 1, year + 1
        else:
            next_month, next_year = month + 1, year

        context.update(
            {
                "year": year,
                "month": month,
                "month_name": MONTH_NAMES_PT[month],
                "month_days": month_days,
                "wo_by_day": wo_by_day,
                "today": today,
                "prev_month": prev_month,
                "prev_year": prev_year,
                "next_month": next_month,
                "next_year": next_year,
                "teams": teams,
                "members": members,
                "current_team": filter_team,
                "current_assigned": filter_assigned,
            }
        )
        return context


# ---------------------------------------------------------------------------
# ServiceType Views (settings)
# ---------------------------------------------------------------------------


class ServiceTypeListView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = ServiceType
    template_name = "operations/service_type_list.html"
    partial_template_name = "operations/partials/_service_type_table.html"
    context_object_name = "service_types"
    paginate_by = 25
