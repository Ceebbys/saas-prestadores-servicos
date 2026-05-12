from django.apps import AppConfig


class CommunicationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.communications"
    verbose_name = "Comunicações"

    def ready(self):
        # Conecta signals de broadcast realtime (Channels).
        # noqa: F401 — import-side-effect intencional
        from apps.communications import signals  # noqa: F401
