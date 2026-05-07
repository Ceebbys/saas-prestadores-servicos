"""Roda os triggers de inatividade manualmente (sem Celery).

Útil para debug ou ambientes onde Celery não está disponível.
"""

from django.core.management.base import BaseCommand

from apps.chatbot.tasks import run_triggers


class Command(BaseCommand):
    help = "Verifica fluxos de inatividade do chatbot e dispara os elegíveis."

    def handle(self, *args, **options):
        result = run_triggers()
        self.stdout.write(self.style.SUCCESS(
            f"OK — disparados: {result['dispatched']} | por empresa: {result['per_empresa']}"
        ))
