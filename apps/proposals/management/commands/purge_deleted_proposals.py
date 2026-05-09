"""Hard-delete proposals soft-deleted há mais de N dias.

Política padrão: 60 dias na lixeira → exclusão definitiva. Cada execução
gera um AutomationLog para auditoria.

Uso:
    python manage.py purge_deleted_proposals          # default 60 dias
    python manage.py purge_deleted_proposals --days 30
    python manage.py purge_deleted_proposals --dry-run
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Exclui definitivamente propostas soft-deleted há mais de N dias."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=60,
            help="Dias na lixeira antes do hard-delete (default 60).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Apenas lista o que seria excluído.",
        )

    def handle(self, *args, **opts):
        from apps.automation.models import AutomationLog
        from apps.proposals.models import Proposal

        days = opts["days"]
        dry_run = opts["dry_run"]
        cutoff = timezone.now() - timedelta(days=days)

        qs = Proposal.all_objects.filter(
            deleted_at__isnull=False, deleted_at__lt=cutoff,
        )
        total = qs.count()
        if total == 0:
            self.stdout.write("Nada a purgar.")
            return

        self.stdout.write(f"{total} proposta(s) na lixeira há mais de {days} dia(s).")
        if dry_run:
            for p in qs[:20]:
                self.stdout.write(
                    f"  • {p.number} (excluída em {p.deleted_at:%Y-%m-%d}) — {p.empresa_id}"
                )
            if total > 20:
                self.stdout.write(f"  ... e mais {total - 20}")
            return

        purged = 0
        for p in qs.iterator():
            try:
                AutomationLog.objects.create(
                    empresa=p.empresa,
                    action=AutomationLog.Action.PROPOSAL_DELETED,
                    entity_type=AutomationLog.EntityType.PROPOSAL,
                    entity_id=p.pk,
                    status=AutomationLog.Status.SUCCESS,
                    metadata={
                        "event": "proposal_purged_from_trash",
                        "number": p.number,
                        "purged_after_days": days,
                    },
                )
                p.hard_delete()
                purged += 1
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(f"Falha ao purgar {p.pk}: {exc}")

        self.stdout.write(self.style.SUCCESS(f"Purgadas: {purged}/{total}"))
