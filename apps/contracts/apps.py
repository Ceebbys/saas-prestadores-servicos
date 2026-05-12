from django.apps import AppConfig


class ContractsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.contracts"
    verbose_name = "Contratos"

    def ready(self) -> None:
        # RV05-F — Carrega signals de ContractStatusHistory
        from apps.contracts import signals  # noqa: F401
