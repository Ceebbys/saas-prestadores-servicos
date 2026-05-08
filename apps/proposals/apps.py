from django.apps import AppConfig


class ProposalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.proposals"
    verbose_name = "Propostas"

    def ready(self):
        # Registra signals (post_init/post_save) que disparam automações.
        from apps.proposals import signals  # noqa: F401
