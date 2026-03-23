"""
Management command para remover dados de demonstração e opcionalmente re-popular.

Uso:
    python manage.py reset_demo_data           # Remove e re-popula
    python manage.py reset_demo_data --no-reseed  # Apenas remove
"""

import os

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Remove todos os dados de demonstração e opcionalmente re-popula"

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-reseed",
            action="store_true",
            help="Apenas remove os dados sem re-popular",
        )

    def handle(self, *args, **options):
        if not self._is_safe_to_run():
            self.stderr.write(self.style.ERROR(
                "Bloqueado: defina DEBUG=True ou DEMO_SEED=true no ambiente."
            ))
            return

        from apps.accounts.models import Empresa, User

        demo_users = User.objects.filter(email__endswith=".demo")
        demo_empresas = Empresa.objects.filter(
            memberships__user__in=demo_users
        ).distinct()

        if not demo_empresas.exists():
            self.stdout.write("Nenhum dado demo encontrado.")
            if not options["no_reseed"]:
                self.stdout.write("Populando dados demo...")
                call_command("seed_demo_data")
            return

        count_empresas = demo_empresas.count()
        count_users = demo_users.count()

        self.stdout.write(
            f"Removendo {count_empresas} empresas demo e {count_users} usuários..."
        )

        with transaction.atomic():
            # Delete opportunities first (PipelineStage uses on_delete=PROTECT)
            from apps.crm.models import Opportunity
            Opportunity.objects.filter(empresa__in=demo_empresas).delete()
            # Delete demo users (not cascade from empresa)
            demo_users.delete()
            # Empresa cascade deletes all TenantOwnedModel children
            demo_empresas.delete()

        self.stdout.write(self.style.SUCCESS("Dados demo removidos com sucesso."))

        if not options["no_reseed"]:
            self.stdout.write("\nRe-populando dados demo...\n")
            call_command("seed_demo_data")

    def _is_safe_to_run(self):
        return (
            getattr(settings, "DEBUG", False)
            or os.environ.get("DEMO_SEED", "").lower() == "true"
        )
