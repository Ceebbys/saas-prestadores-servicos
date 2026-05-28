from django.apps import AppConfig


class OperationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.operations"
    verbose_name = "Operações"

    def ready(self) -> None:
        # RV10 — Carrega signals que disparam PipelineAutomationRule a partir
        # de mudanças de status da Ordem de Serviço.
        from apps.operations import signals  # noqa: F401
