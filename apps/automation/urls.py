from django.urls import path

from . import views

app_name = "automation"

urlpatterns = [
    path("", views.PipelineDemoView.as_view(), name="pipeline_demo"),
    path("run/", views.RunPipelineView.as_view(), name="run_pipeline"),
    path("logs/", views.AutomationLogListView.as_view(), name="log_list"),
]
