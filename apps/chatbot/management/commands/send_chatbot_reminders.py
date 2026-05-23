"""RV06 — Manda lembretes para sessões idle.

Uso: python manage.py send_chatbot_reminders [--verbose]

Configurar via cron (a cada 5 minutos):
    */5 * * * * cd /opt/saas-prestadores && python manage.py send_chatbot_reminders

Cada bloco de input no construtor visual pode ter:
- reminder_minutes (0=desativado)
- reminder_message

Quando a sessão fica idle além do reminder_minutes, este comando envia
a mensagem. Idempotente: marca reminder_sent_at para não duplicar.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Envia lembretes para sessões idle de chatbot com reminder configurado."

    def add_arguments(self, parser):
        parser.add_argument(
            "--verbose", action="store_true",
            help="Imprime stats detalhadas no stdout.",
        )

    def handle(self, *args, **options):
        from apps.chatbot.reminders import send_idle_reminders
        stats = send_idle_reminders()
        if options.get("verbose"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"reminders: checked={stats['checked']} "
                    f"sent={stats['sent']} "
                    f"skipped={stats['skipped']} "
                    f"errors={stats['errors']}"
                )
            )
        elif stats["sent"] > 0 or stats["errors"] > 0:
            self.stdout.write(
                f"reminders: {stats['sent']} enviados, {stats['errors']} erros."
            )
