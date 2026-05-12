"""RV05-G — Cobertura de Lead.restore() (auditoria apontou gap)."""
from django.test import TestCase
from django.utils import timezone

from apps.crm.models import Lead
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


class LeadRestoreTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("r@t.com", "R", self.empresa)
        create_pipeline_for_empresa(self.empresa)

    def test_restore_removes_deleted_at(self):
        lead = Lead.objects.create(empresa=self.empresa, name="ToRestore")
        lead.delete()  # soft
        self.assertIsNotNone(lead.deleted_at)
        self.assertFalse(Lead.objects.filter(pk=lead.pk).exists())
        # Restore via método do mixin
        lead.restore()
        self.assertIsNone(lead.deleted_at)
        self.assertTrue(Lead.objects.filter(pk=lead.pk).exists())

    def test_restore_idempotent(self):
        """Restore em lead não-deletado não quebra."""
        lead = Lead.objects.create(empresa=self.empresa, name="Active")
        self.assertIsNone(lead.deleted_at)
        lead.restore()  # no-op
        lead.refresh_from_db()
        self.assertIsNone(lead.deleted_at)

    def test_restore_after_cascade_only_restores_lead(self):
        """Restaurar lead não desfaz o cascade (opportunities + drafts).

        Limitação documentada: cascade é one-way. Restaurar só limpa o
        deleted_at do próprio Lead. Filhos precisam restore individual.
        """
        from apps.crm.models import Opportunity, Pipeline
        pipeline = Pipeline.objects.filter(empresa=self.empresa).first()
        stage = pipeline.stages.first()
        lead = Lead.objects.create(empresa=self.empresa, name="X", pipeline_stage=stage)
        # Cria opportunity (current_stage é o nome correto do campo)
        opp = Opportunity.objects.create(
            empresa=self.empresa, lead=lead,
            pipeline=pipeline, current_stage=stage,
            title="Op1", value=100,
        )
        opp_pk = opp.pk
        # Cascade soft-delete: opportunity vai junto (hard)
        lead.delete()
        self.assertFalse(Opportunity.objects.filter(pk=opp_pk).exists())
        # Restaurar lead
        lead.restore()
        # Opportunity continua removida (cascade não é reversível pelo restore)
        self.assertFalse(Opportunity.objects.filter(pk=opp_pk).exists())
