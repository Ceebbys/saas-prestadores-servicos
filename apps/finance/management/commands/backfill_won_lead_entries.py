"""RV10 — Management command: backfill de FinancialEntry para leads ganhos sem entry.

Uso:
    python manage.py backfill_won_lead_entries           # todas as empresas
    python manage.py backfill_won_lead_entries --empresa=slug   # uma só
    python manage.py backfill_won_lead_entries --dry-run        # apenas conta

Cliente reportou: "fechei 3 leads sem proposta mas não aparecem na previsão".
Causa típica: leads já estavam em won_stage antes do signal RV06 entrar, ou
foram movidos por scripts/imports bypassando o signal.

Idempotente: pode ser rodado várias vezes sem duplicar entries.
"""
from django.core.management.base import BaseCommand

from apps.accounts.models import Empresa
from apps.finance.services import (
    backfill_won_lead_entries,
    count_won_leads_without_entry,
)


class Command(BaseCommand):
    help = (
        "Cria FinancialEntry pendente para leads em stage com is_won=True "
        "que ainda não têm lançamento financeiro."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--empresa", type=str, default=None,
            help="Slug de uma empresa específica (default: todas)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Apenas conta sem criar lançamentos",
        )

    def handle(self, *args, **options):
        empresa_slug = options.get("empresa")
        dry_run = options.get("dry_run", False)

        if empresa_slug:
            empresas = Empresa.objects.filter(slug=empresa_slug)
            if not empresas.exists():
                self.stderr.write(
                    self.style.ERROR(f"Empresa '{empresa_slug}' não encontrada.")
                )
                return
        else:
            empresas = Empresa.objects.all()

        total_scanned = 0
        total_created = 0
        total_skipped = 0
        for empresa in empresas:
            pending = count_won_leads_without_entry(empresa)
            if pending == 0:
                self.stdout.write(
                    f"  • {empresa.name} ({empresa.slug}): nenhum pendente."
                )
                continue
            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"  • {empresa.name} ({empresa.slug}): {pending} "
                        f"lead(s) ganhos sem lançamento (DRY-RUN)."
                    )
                )
                total_scanned += pending
                continue
            result = backfill_won_lead_entries(empresa)
            scanned = result["scanned"]
            created = len(result["created"])
            skipped = result["skipped"]
            total_scanned += scanned
            total_created += created
            total_skipped += skipped
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ {empresa.name} ({empresa.slug}): "
                    f"{created} criado(s), {skipped} pulado(s), "
                    f"{scanned} escaneado(s)."
                )
            )

        action = "Identificados" if dry_run else "Processados"
        self.stdout.write(
            self.style.NOTICE(
                f"\n{action} {total_scanned} lead(s) ganhos em "
                f"{empresas.count()} empresa(s)."
            )
        )
        if not dry_run:
            self.stdout.write(
                f"  • Criados: {total_created}\n  • Pulados: {total_skipped}"
            )
