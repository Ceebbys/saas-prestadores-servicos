from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views import View
from django.views.generic import ListView, TemplateView

from apps.core.mixins import EmpresaMixin, HtmxResponseMixin

from .models import AutomationLog
from .services import run_full_pipeline


class PipelineDemoView(EmpresaMixin, TemplateView):
    """Página visual do pipeline automatizado com opção de simulação."""

    template_name = "automation/pipeline_demo.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["recent_logs"] = AutomationLog.objects.filter(
            empresa=self.request.empresa,
            action=AutomationLog.Action.FULL_PIPELINE,
        )[:5]
        return context


class RunPipelineView(EmpresaMixin, View):
    """Executa a simulação do pipeline completo (POST only)."""

    def post(self, request, *args, **kwargs):
        try:
            result = run_full_pipeline(request.empresa)
            context = {
                "result": result,
                "empresa": request.empresa,
                "success": True,
            }

            if request.htmx:
                from django.template.loader import render_to_string
                html = render_to_string(
                    "automation/partials/_pipeline_result.html",
                    context,
                    request=request,
                )
                from django.http import HttpResponse
                return HttpResponse(html)

            messages.success(request, "Pipeline executado com sucesso!")

        except Exception as e:
            if request.htmx:
                from django.template.loader import render_to_string
                from django.http import HttpResponse
                html = render_to_string(
                    "automation/partials/_pipeline_result.html",
                    {"success": False, "error": str(e), "empresa": request.empresa},
                    request=request,
                )
                return HttpResponse(html)

            messages.error(request, f"Erro ao executar pipeline: {e}")

        return HttpResponseRedirect(reverse("automation:pipeline_demo"))


class AutomationLogListView(EmpresaMixin, HtmxResponseMixin, ListView):
    """Histórico de automações executadas."""

    model = AutomationLog
    template_name = "automation/log_list.html"
    partial_template_name = "automation/partials/_log_table.html"
    context_object_name = "logs"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset()
        action = self.request.GET.get("action")
        status = self.request.GET.get("status")
        if action:
            qs = qs.filter(action=action)
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["action_choices"] = AutomationLog.Action.choices
        context["status_choices"] = AutomationLog.Status.choices
        context["current_action"] = self.request.GET.get("action", "")
        context["current_status"] = self.request.GET.get("status", "")
        return context
