"""RV07 — Item 4.1: checklist dentro do Lead (criar/marcar/editar)."""
import json

from django.test import TestCase
from django.urls import reverse

from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.forms import LeadForm
from apps.crm.models import Lead, LeadChecklist, Pipeline, PipelineStage


class LeadChecklistFormTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-checklist")
        self.pipeline = Pipeline.objects.create(
            empresa=self.empresa, name="Vendas", is_default=True,
        )
        self.stage = PipelineStage.objects.create(
            pipeline=self.pipeline, name="Novo", order=0,
        )

    def _new_contact_form(self, checklist, instance=None):
        data = {
            "name": "Lead com checklist",
            "source": "site",
            "pipeline_stage": self.stage.pk,
            "contact_mode": "new",
            "new_contato_name": "Contato X",
            "checklist_json": json.dumps(checklist),
        }
        return LeadForm(data=data, instance=instance, empresa=self.empresa)

    def test_create_lead_with_checklist_items(self):
        items = [
            {"description": "Levantamento realizado", "is_completed": False},
            {"description": "Memorial concluído", "is_completed": False},
            {"description": "Revisão técnica", "is_completed": False},
        ]
        form = self._new_contact_form(items)
        self.assertTrue(form.is_valid(), form.errors)
        lead = form.save()
        self.assertEqual(lead.checklist_items.count(), 3)
        self.assertEqual(
            list(lead.checklist_items.values_list("description", flat=True)),
            ["Levantamento realizado", "Memorial concluído", "Revisão técnica"],
        )

    def test_edit_reconciles_checklist(self):
        from apps.contacts.models import Contato
        contato = Contato.objects.create(empresa=self.empresa, name="Dono")
        lead = Lead.objects.create(
            empresa=self.empresa, name="L", pipeline_stage=self.stage, contato=contato,
        )
        i1 = LeadChecklist.objects.create(lead=lead, description="Antigo 1", order=0)
        i2 = LeadChecklist.objects.create(lead=lead, description="Antigo 2", order=1)
        items = [
            {"id": i1.id, "description": "Antigo 1 editado", "is_completed": False},
            {"description": "Novo item", "is_completed": False},
        ]
        data = {
            "name": "L",
            "source": "site",
            "pipeline_stage": self.stage.pk,
            "contact_mode": "search",
            "contato": contato.pk,
            "checklist_json": json.dumps(items),
        }
        form = LeadForm(data=data, instance=lead, empresa=self.empresa)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        descrs = set(lead.checklist_items.values_list("description", flat=True))
        self.assertEqual(descrs, {"Antigo 1 editado", "Novo item"})
        self.assertFalse(LeadChecklist.objects.filter(id=i2.id).exists())

    def test_empty_description_ignored(self):
        items = [
            {"description": "Válido", "is_completed": False},
            {"description": "   ", "is_completed": False},
        ]
        form = self._new_contact_form(items)
        self.assertTrue(form.is_valid(), form.errors)
        lead = form.save()
        self.assertEqual(lead.checklist_items.count(), 1)


class LeadChecklistToggleViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-toggle")
        self.user = create_test_user("t@t.com", "T", self.empresa)
        self.client.force_login(self.user)
        self.lead = Lead.objects.create(empresa=self.empresa, name="L")
        self.item = LeadChecklist.objects.create(lead=self.lead, description="Item")

    def test_toggle_marks_completed_and_back(self):
        url = reverse("crm:lead_checklist_toggle", args=[self.lead.pk, self.item.pk])
        self.client.post(url)
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_completed)
        self.assertIsNotNone(self.item.completed_at)
        self.client.post(url)
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_completed)
        self.assertIsNone(self.item.completed_at)

    def test_toggle_cross_tenant_404(self):
        other = create_test_empresa(slug="rv07-other")
        other_user = create_test_user("o@t.com", "O", other)
        self.client.force_login(other_user)
        url = reverse("crm:lead_checklist_toggle", args=[self.lead.pk, self.item.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)
