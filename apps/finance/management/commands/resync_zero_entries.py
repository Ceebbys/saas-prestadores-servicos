"""RV07 — Re-puxa o valor de lançamentos auto-gerados que ficaram em R$ 0,00.

Uso:
    python manage.py resync_zero_entries            # todas as empresas
    python manage.py resync_zero_entries --empresa 3
    python manage.py resync_zero_entries --dry-run  # só mostra, não grava
"""
from django.core.management.base import BaseCommand

from apps.finance.models import FinancialEntry
from apps.finance.services import _resolve_lead_value, resync_zero_value_entries


class Command(BaseCommand):
    help = "Re-puxa o valor de lançamentos auto-gerados zerados (RV07)."

    def add_arguments(self, parser):
        parser.add_argument("--empresa", type=int, default=None, help="ID da empresa (default: todas).")
        parser.add_argument("--dry-run", action="store_true", help="Apenas lista o que seria alterado.")

    def handle(self, *args, **opts):
        empresa_id = opts.get("empresa")
        empresa = None
        if empresa_id:
            from apps.accounts.models import Empresa
            empresa = Empresa.objects.filter(pk=empresa_id).first()
            if empresa is None:
                self.stderr.write(f"Empresa {empresa_id} não encontrada.")
                return

        if opts.get("dry_run"):
            qs = FinancialEntry.objects.filter(
                auto_generated=True, amount=0, related_lead__isnull=False,
            ).select_related("related_lead", "related_lead__servico")
            if empresa is not None:
                qs = qs.filter(empresa=empresa)
            n = 0
            for entry in qs:
                value = _resolve_lead_value(entry.related_lead)
                if value and value > 0:
                    n += 1
                    self.stdout.write(
                        f"  [dry] entry {entry.pk} (lead {entry.related_lead_id}): 0,00 -> R$ {value}"
                    )
            self.stdout.write(self.style.WARNING(f"DRY-RUN: {n} seriam atualizados."))
            return

        result = resync_zero_value_entries(empresa)
        for pk, value in result["updated"]:
            self.stdout.write(f"  entry {pk} -> R$ {value}")
        self.stdout.write(self.style.SUCCESS(
            f"Atualizados: {len(result['updated'])} (de {result['scanned']} zerados varridos)."
        ))
