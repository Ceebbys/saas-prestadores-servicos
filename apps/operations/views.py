import calendar as cal_module
import logging
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
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

from .forms import ServiceTypeForm, WorkOrderForm, WorkOrderTimeLogForm
from .models import (
    ServiceType,
    Team,
    WorkOrder,
    WorkOrderChecklist,
    WorkOrderTimeLog,
)


# ---------------------------------------------------------------------------
# Time tracker helpers (RV07 3.1)
# ---------------------------------------------------------------------------


def _format_hm(seconds: int) -> str:
    """Segundos → 'Hh MMmin' (ex.: 9000 → '2h 30min')."""
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h {m:02d}min"


def time_section_context(work_order, user):
    """Contexto consistente da seção 'Tempo / Horas' da OS — usado pela
    DetailView e pelas ações de cronômetro/manual (HTMX)."""
    logs = list(work_order.time_logs.select_related("user").all())
    total_seconds = sum(log.live_duration_seconds for log in logs)
    billable_total = sum((log.billable_value for log in logs), Decimal("0.00"))
    user_id = getattr(user, "id", None)
    running = next(
        (log for log in logs if log.is_running and log.user_id == user_id), None,
    )
    return {
        "work_order": work_order,
        "time_logs": logs,
        "time_total_seconds": total_seconds,
        "time_total_display": _format_hm(total_seconds),
        "time_billable_total": billable_total,
        "running_log": running,
        "running_started_ts": int(running.started_at.timestamp()) if running else 0,
        "time_no_rate": bool(logs) and not any(log.rate_source for log in logs),
    }


def _render_time_section(request, work_order):
    return render_to_string(
        "operations/partials/_time_section.html",
        time_section_context(work_order, request.user),
        request=request,
    )


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
            .prefetch_related("checklist_items", "time_logs__user")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        items = self.object.checklist_items.all()
        total = len(items)
        completed = sum(1 for i in items if i.is_completed)
        context["checklist_total"] = total
        context["checklist_completed"] = completed
        context["checklist_pct"] = int((completed / total) * 100) if total else 0
        # RV07 (3.1) — seção de Tempo / Horas
        context.update(time_section_context(self.object, self.request.user))
        return context


def _service_type_prazos_json(empresa):
    """RV10 — Mapa {service_type_id: default_prazo_dias} pro frontend
    auto-popular `expected_end_date` quando o user seleciona o serviço.

    Serializado como JSON pra Alpine.js ler direto no x-data.
    """
    import json
    items = ServiceType.objects.filter(
        empresa=empresa, is_active=True,
        default_prazo_dias__isnull=False,
    ).values("pk", "default_prazo_dias")
    return json.dumps({
        str(item["pk"]): item["default_prazo_dias"] for item in items
    })


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

    def get_context_data(self, **kwargs):
        # RV10 — Mapa de prazos pro Alpine.js auto-calcular previsão de término
        context = super().get_context_data(**kwargs)
        context["service_type_prazos_json"] = _service_type_prazos_json(
            self.request.empresa,
        )
        return context

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
        # EPIC 7 hook (groundwork — deferido): criar pasta do projeto no
        # armazenamento em nuvem conectado (Google Drive / OneDrive) e anexar
        # o link em self.object.cloud_storage_links. No-op até haver provedor
        # conectado (apps.integrations.services.create_workorder_folder).
        # from apps.integrations.services import create_workorder_folder
        # result = create_workorder_folder(self.object)
        # if result.get("integration_ready") and result.get("share_url"):
        #     self.object.cloud_storage_links.append(result["share_url"])
        #     self.object.save(update_fields=["cloud_storage_links", "updated_at"])
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["service_type_prazos_json"] = _service_type_prazos_json(
            self.request.empresa,
        )
        return context

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
            # RV07 (6.2) — notifica serviço iniciado/concluído
            from apps.communications.notifications_events import (
                notify_service_completed,
                notify_service_started,
            )
            if new_status == WorkOrder.Status.IN_PROGRESS:
                notify_service_started(work_order)
            elif new_status == WorkOrder.Status.COMPLETED:
                notify_service_completed(work_order)
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
# Time tracker views (RV07 3.1)
# ---------------------------------------------------------------------------


class WorkOrderTimerStartView(EmpresaMixin, View):
    """Inicia o cronômetro da OS para o usuário atual (idempotente)."""

    def post(self, request, wo_pk):
        from django.db import IntegrityError, transaction

        work_order = get_object_or_404(WorkOrder, pk=wo_pk, empresa=request.empresa)
        try:
            with transaction.atomic():
                WorkOrderTimeLog.objects.get_or_create(
                    work_order=work_order,
                    user=request.user,
                    ended_at__isnull=True,
                    defaults={
                        "started_at": timezone.now(),
                        "source": WorkOrderTimeLog.Source.TIMER,
                        "is_billable": True,
                    },
                )
        except IntegrityError:
            pass  # corrida: já existe um cronômetro rodando — segue idempotente

        # Auto-avança para "Em andamento" (estilo ClickUp), só de etapas
        # iniciais e nunca de OS concluída/cancelada.
        if work_order.status in (
            WorkOrder.Status.PENDING, WorkOrder.Status.SCHEDULED,
        ):
            work_order.status = WorkOrder.Status.IN_PROGRESS
            work_order.save(update_fields=["status", "updated_at"])
            # Pente fino: iniciar o cronômetro é a forma mais comum de "começar
            # o serviço" — notifica "Serviço iniciado" igual à mudança manual de
            # status. Só dispara dentro do if (transição real), sem duplicar.
            from apps.communications.notifications_events import notify_service_started
            notify_service_started(work_order)

        if request.htmx:
            return HttpResponse(_render_time_section(request, work_order))
        return redirect("operations:work_order_detail", pk=work_order.pk)


class WorkOrderTimerStopView(EmpresaMixin, View):
    """Para o cronômetro em execução (encerra o intervalo) e fixa a tarifa."""

    def post(self, request, wo_pk, log_pk):
        from apps.operations.services import resolve_hour_rate

        work_order = get_object_or_404(WorkOrder, pk=wo_pk, empresa=request.empresa)
        log = get_object_or_404(
            WorkOrderTimeLog, pk=log_pk, work_order=work_order,
            ended_at__isnull=True,
        )
        log.ended_at = timezone.now()
        log.recompute_duration()
        log.rate_applied, log.rate_source = resolve_hour_rate(
            work_order.empresa, log.user,
        )
        log.save()

        if request.htmx:
            return HttpResponse(_render_time_section(request, work_order))
        return redirect("operations:work_order_detail", pk=work_order.pk)


class WorkOrderTimeLogCreateView(EmpresaMixin, View):
    """Lançamento manual de horas."""

    def get(self, request, wo_pk):
        work_order = get_object_or_404(WorkOrder, pk=wo_pk, empresa=request.empresa)
        return render(request, "operations/time_log_form.html", {
            "work_order": work_order, "form": WorkOrderTimeLogForm(),
        })

    def post(self, request, wo_pk):
        from apps.operations.services import resolve_hour_rate

        work_order = get_object_or_404(WorkOrder, pk=wo_pk, empresa=request.empresa)
        form = WorkOrderTimeLogForm(request.POST)
        if not form.is_valid():
            return render(request, "operations/time_log_form.html", {
                "work_order": work_order, "form": form,
            })
        log = form.save(commit=False)
        log.work_order = work_order
        log.user = request.user
        log.source = WorkOrderTimeLog.Source.MANUAL
        log.recompute_duration()
        log.rate_applied, log.rate_source = resolve_hour_rate(
            work_order.empresa, log.user,
        )
        log.save()
        messages.success(request, "Horas lançadas com sucesso.")
        return redirect("operations:work_order_detail", pk=work_order.pk)


class WorkOrderTimeLogUpdateView(EmpresaMixin, View):
    """Edita um apontamento (manual ou já encerrado)."""

    def _get_objects(self, request, wo_pk, log_pk):
        work_order = get_object_or_404(WorkOrder, pk=wo_pk, empresa=request.empresa)
        log = get_object_or_404(WorkOrderTimeLog, pk=log_pk, work_order=work_order)
        return work_order, log

    def get(self, request, wo_pk, log_pk):
        work_order, log = self._get_objects(request, wo_pk, log_pk)
        return render(request, "operations/time_log_form.html", {
            "work_order": work_order, "form": WorkOrderTimeLogForm(instance=log),
            "log": log,
        })

    def post(self, request, wo_pk, log_pk):
        from apps.operations.services import resolve_hour_rate

        work_order, log = self._get_objects(request, wo_pk, log_pk)
        form = WorkOrderTimeLogForm(request.POST, instance=log)
        if not form.is_valid():
            return render(request, "operations/time_log_form.html", {
                "work_order": work_order, "form": form, "log": log,
            })
        log = form.save(commit=False)
        log.recompute_duration()
        # Pente fino: preserva o snapshot da tarifa (preço histórico). Editar
        # uma observação/duração NÃO re-precifica pela tarifa atual da empresa
        # (que pode ter mudado). O valor faturável recalcula via property
        # (duração × tarifa fixada). Só resolve se ainda não houver tarifa.
        if log.rate_applied is None:
            log.rate_applied, log.rate_source = resolve_hour_rate(
                work_order.empresa, log.user,
            )
        log.save()
        messages.success(request, "Apontamento atualizado.")
        return redirect("operations:work_order_detail", pk=work_order.pk)


class WorkOrderTimeLogDeleteView(EmpresaMixin, View):
    """Remove um apontamento de horas."""

    http_method_names = ["post"]

    def post(self, request, wo_pk, log_pk):
        work_order = get_object_or_404(WorkOrder, pk=wo_pk, empresa=request.empresa)
        log = get_object_or_404(WorkOrderTimeLog, pk=log_pk, work_order=work_order)
        log.delete()
        if request.htmx:
            return HttpResponse(_render_time_section(request, work_order))
        messages.success(request, "Apontamento removido.")
        return redirect("operations:work_order_detail", pk=work_order.pk)


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
        import logging

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

        # RV05-H — usa render_html_to_pdf do core (url_fetcher seguro:
        # bloqueia file://, ftp://, data: malicioso; resolve /media/ via
        # default_storage). Paridade total com Proposta e Contrato.
        from apps.core.document_render.pdf import render_html_to_pdf
        from django.contrib import messages
        from django.shortcuts import redirect

        try:
            base_url = request.build_absolute_uri("/")
            pdf = render_html_to_pdf(html_string, base_url=base_url)
        except ValueError as exc:
            messages.error(request, f"Não foi possível gerar PDF: {exc}")
            return redirect("operations:work_order_detail", pk=wo.pk)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception(
                "Falha inesperada ao gerar PDF da OS %s (%s)",
                wo.pk, wo.number,
            )
            messages.error(
                request,
                "Não foi possível gerar o PDF agora. Tente novamente — se persistir, contate o suporte.",
            )
            return redirect("operations:work_order_detail", pk=wo.pk)

        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="OS-{wo.number}.pdf"'
        )
        return response


# ---------------------------------------------------------------------------
# Calendar View
# ---------------------------------------------------------------------------


logger = logging.getLogger(__name__)


def _google_event_days(ev: dict, year: int, month: int) -> list[int]:
    """RV07 (Epic 7) — dias (do mês) que um evento Google ocupa.

    Aceita eventos all-day (fim exclusivo) e com horário (mostra no dia inicial).
    Retorna a lista de números de dia que caem em (year, month).
    """
    import datetime as _dt

    def _parse(s):
        if not s:
            return None
        try:
            return _dt.date.fromisoformat(str(s)[:10])  # 'YYYY-MM-DD' de date ou dateTime
        except ValueError:
            return None

    start = _parse(ev.get("start"))
    if start is None:
        return []
    if ev.get("all_day"):
        end = _parse(ev.get("end")) or (start + _dt.timedelta(days=1))
        last = end - _dt.timedelta(days=1)  # all-day: fim é exclusivo
    else:
        last = start

    days = []
    cur = start
    while cur <= last:
        if cur.year == year and cur.month == month:
            days.append(cur.day)
        cur += _dt.timedelta(days=1)
    return days


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

        # RV10 — Cliente pediu: "ai vai para o calendario e ocara vê quem ta
        # garrado ou não". Agora consideramos OS que SE SOBREPÕEM ao mês:
        # scheduled_date <= último_dia E (expected_end_date IS NULL OR
        # expected_end_date >= primeiro_dia). Mostramos a OS em TODOS os
        # dias do range que caem no mês.
        from datetime import date as _date
        from calendar import monthrange as _monthrange
        first_day = _date(year, month, 1)
        last_day_num = _monthrange(year, month)[1]
        last_day = _date(year, month, last_day_num)

        work_orders = WorkOrder.objects.filter(
            empresa=self.request.empresa,
            scheduled_date__isnull=False,
            scheduled_date__lte=last_day,
        ).filter(
            # expected_end_date >= primeiro_dia OU NULL (1-dia, mostra só no dia inicial)
            Q(expected_end_date__gte=first_day) |
            Q(expected_end_date__isnull=True, scheduled_date__gte=first_day),
        ).select_related("assigned_to", "assigned_team", "service_type")

        # Apply filters
        filter_team = self.request.GET.get("team", "").strip()
        filter_assigned = self.request.GET.get("assigned_to", "").strip()
        if filter_team:
            work_orders = work_orders.filter(assigned_team_id=filter_team)
        if filter_assigned:
            work_orders = work_orders.filter(assigned_to_id=filter_assigned)

        # Group by day — espalha a OS por todos os dias do range que caem no mês
        from datetime import timedelta as _td
        wo_by_day: dict = {}
        for wo in work_orders:
            start = wo.scheduled_date
            end = wo.expected_end_date or start
            # Clipa o range ao mês atual
            range_start = max(start, first_day)
            range_end = min(end, last_day)
            day = range_start
            while day <= range_end:
                wo_by_day.setdefault(day.day, []).append(wo)
                day = day + _td(days=1)

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

        # RV07 (Epic 7) — sobrepõe eventos da agenda Google conectada (leitura).
        # Falha/ausência de integração → Calendário segue mostrando só as OS.
        google_by_day: dict = {}
        google_connected = False
        try:
            import datetime as _dtmod

            from apps.integrations.services import (
                get_calendar_provider,
                list_calendar_events,
            )

            google_connected = get_calendar_provider(self.request.empresa) is not None
            if google_connected:
                tmin = timezone.make_aware(_dtmod.datetime(year, month, 1))
                if month == 12:
                    tmax = timezone.make_aware(_dtmod.datetime(year + 1, 1, 1))
                else:
                    tmax = timezone.make_aware(_dtmod.datetime(year, month + 1, 1))
                for ev in list_calendar_events(
                    self.request.empresa, time_min=tmin, time_max=tmax,
                ):
                    for day_num in _google_event_days(ev, year, month):
                        google_by_day.setdefault(day_num, []).append(ev)
        except Exception:  # noqa: BLE001
            logger.exception("calendar google overlay failed")

        context.update(
            {
                "year": year,
                "month": month,
                "month_name": MONTH_NAMES_PT[month],
                "month_days": month_days,
                "wo_by_day": wo_by_day,
                "google_by_day": google_by_day,
                "google_connected": google_connected,
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
