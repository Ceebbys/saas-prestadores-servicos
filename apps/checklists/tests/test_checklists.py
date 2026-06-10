"""RV08 (2.1/2.2) — Múltiplos checklists (Trello-style) na Pipeline e na OS."""
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from apps.checklists.models import Checklist, ChecklistItem
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)
from apps.crm.models import Lead, Opportunity
from apps.operations.models import WorkOrder


class ChecklistRV08Tests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv08-cl")
        self.user = create_test_user("cl@t.com", "CL", self.empresa)
        self.client.force_login(self.user)
        self.pipeline, self.stage, *_ = create_pipeline_for_empresa(self.empresa)
        self.lead = Lead.objects.create(empresa=self.empresa, name="Lead CL")
        self.opp = Opportunity.objects.create(
            empresa=self.empresa, lead=self.lead, pipeline=self.pipeline,
            current_stage=self.stage, title="Op CL",
        )
        self.wo = WorkOrder.objects.create(empresa=self.empresa, title="OS CL")

    def _opp_ct(self):
        return ContentType.objects.get_for_model(Opportunity)

    def test_add_multiple_checklists_to_opportunity(self):
        url = reverse("checklists:add", args=["opportunity", self.opp.pk])
        self.client.post(url, {"name": "Revisão Técnica 01"})
        self.client.post(url, {"name": "Documentação"})
        cls = Checklist.objects.filter(
            content_type=self._opp_ct(), object_id=self.opp.pk,
        )
        self.assertEqual(cls.count(), 2)
        self.assertEqual(cls.first().empresa, self.empresa)

    def test_item_lifecycle(self):
        checklist = Checklist.objects.create(
            empresa=self.empresa, content_type=self._opp_ct(),
            object_id=self.opp.pk, name="C1",
        )
        # add item
        self.client.post(
            reverse("checklists:item_add", args=[checklist.pk]),
            {"description": "Levantamento"},
        )
        item = ChecklistItem.objects.get(checklist=checklist)
        self.assertEqual(item.description, "Levantamento")
        # toggle
        self.client.post(reverse("checklists:item_toggle", args=[item.pk]))
        item.refresh_from_db()
        self.assertTrue(item.is_completed)
        self.assertIsNotNone(item.completed_at)
        # edit
        self.client.post(
            reverse("checklists:item_edit", args=[item.pk]),
            {"description": "Levantamento topográfico"},
        )
        item.refresh_from_db()
        self.assertEqual(item.description, "Levantamento topográfico")
        # delete
        self.client.post(reverse("checklists:item_delete", args=[item.pk]))
        self.assertFalse(ChecklistItem.objects.filter(pk=item.pk).exists())

    def test_delete_checklist(self):
        checklist = Checklist.objects.create(
            empresa=self.empresa, content_type=self._opp_ct(),
            object_id=self.opp.pk, name="C1",
        )
        self.client.post(reverse("checklists:delete", args=[checklist.pk]))
        self.assertFalse(Checklist.objects.filter(pk=checklist.pk).exists())

    def test_progress_helper(self):
        checklist = Checklist.objects.create(
            empresa=self.empresa, content_type=self._opp_ct(),
            object_id=self.opp.pk, name="C1",
        )
        ChecklistItem.objects.create(checklist=checklist, description="a", is_completed=True)
        ChecklistItem.objects.create(checklist=checklist, description="b")
        prog = self.opp.checklist_progress()
        self.assertEqual(prog, {"completed": 1, "total": 2})

    def test_work_order_owner(self):
        url = reverse("checklists:add", args=["work_order", self.wo.pk])
        self.client.post(url, {"name": "Execução"})
        wo_ct = ContentType.objects.get_for_model(WorkOrder)
        self.assertEqual(
            Checklist.objects.filter(content_type=wo_ct, object_id=self.wo.pk).count(),
            1,
        )

    def test_tenant_isolation(self):
        other = create_test_empresa(slug="rv08-cl-other")
        create_test_user("o@t.com", "O", other)
        pipe, st, *_ = create_pipeline_for_empresa(other)
        lead_o = Lead.objects.create(empresa=other, name="L")
        opp_o = Opportunity.objects.create(
            empresa=other, lead=lead_o, pipeline=pipe, current_stage=st, title="X",
        )
        # user A tenta criar checklist na oportunidade da empresa B
        resp = self.client.post(
            reverse("checklists:add", args=["opportunity", opp_o.pk]),
            {"name": "Hack"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_detail_pages_render_checklist_block(self):
        resp_opp = self.client.get(reverse("crm:opportunity_detail", args=[self.opp.pk]))
        self.assertContains(resp_opp, f"checklists-opportunity-{self.opp.pk}")
        resp_wo = self.client.get(reverse("operations:work_order_detail", args=[self.wo.pk]))
        self.assertContains(resp_wo, f"checklists-work_order-{self.wo.pk}")
