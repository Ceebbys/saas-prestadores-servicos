"""RV09 — Testes do checklist editável no form da OS.

Bug reportado pelo cliente: detail da OS exibe seção 'Checklist' mas o form
de edição não permite adicionar/remover/reordenar itens.

Cobre:
- Form aceita JSON vazio (sem checklist)
- Cria items novos a partir do JSON
- Atualiza description de items existentes (mantém ID)
- Deleta items removidos do JSON
- Mantém `is_completed` quando o item já existia
- `order` reflete a posição no JSON
- Items com description vazia são ignorados silenciosamente
- JSON malformado retorna ValidationError
- Edição via view atualiza checklist (smoke end-to-end)
"""
import json

from django.test import Client, TestCase
from django.urls import reverse

from apps.crm.models import Lead, Pipeline, PipelineStage
from apps.operations.forms import WorkOrderForm
from apps.operations.models import WorkOrder, WorkOrderChecklist
from apps.core.tests.helpers import create_test_empresa, create_test_user


def _make_lead(empresa):
    """Cria pipeline+stage+lead pronto para vincular em uma WO."""
    pipeline = Pipeline.objects.create(empresa=empresa, name="P", is_default=True)
    stage = PipelineStage.objects.create(pipeline=pipeline, name="Novo", order=0)
    return Lead.objects.create(
        empresa=empresa, name="Cliente X", phone="11999990000",
        pipeline_stage=stage,
    )


class WorkOrderFormChecklistTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv09-form")
        self.user = create_test_user("a@t.com", "A", self.empresa)
        self.lead = _make_lead(self.empresa)

    def _base_data(self, **overrides):
        """Payload mínimo do form com campos obrigatórios."""
        data = {
            "title": "OS de teste",
            "lead": self.lead.pk,
            "priority": "medium",
            "description": "desc",
            "checklist_json": "[]",
        }
        data.update(overrides)
        return data

    def test_form_accepts_empty_checklist(self):
        form = WorkOrderForm(
            data=self._base_data(checklist_json=""), empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.instance.empresa = self.empresa
        wo = form.save()
        self.assertEqual(wo.checklist_items.count(), 0)

    def test_form_creates_new_items_from_json(self):
        items = [
            {"description": "Verificar materiais"},
            {"description": "Conferir equipamentos"},
            {"description": "Tirar fotos antes"},
        ]
        form = WorkOrderForm(
            data=self._base_data(checklist_json=json.dumps(items)),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.instance.empresa = self.empresa
        wo = form.save()
        self.assertEqual(wo.checklist_items.count(), 3)
        descriptions = list(
            wo.checklist_items.order_by("order").values_list("description", flat=True)
        )
        self.assertEqual(
            descriptions,
            ["Verificar materiais", "Conferir equipamentos", "Tirar fotos antes"],
        )
        # `order` reflete a posição no array
        orders = list(
            wo.checklist_items.order_by("order").values_list("order", flat=True)
        )
        self.assertEqual(orders, [0, 1, 2])

    def test_form_updates_existing_item_description(self):
        # Cria OS + item existente
        wo = WorkOrder.objects.create(
            empresa=self.empresa, title="OS", lead=self.lead,
            priority="medium",
        )
        existing = WorkOrderChecklist.objects.create(
            work_order=wo, description="Antigo", is_completed=True, order=0,
        )
        # Edita o item via form (mantém ID, muda description)
        items = [{"id": existing.pk, "description": "Novo nome"}]
        form = WorkOrderForm(
            data=self._base_data(checklist_json=json.dumps(items)),
            instance=wo, empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        existing.refresh_from_db()
        self.assertEqual(existing.description, "Novo nome")
        # is_completed preservado (não foi enviado)
        self.assertTrue(existing.is_completed)
        # Não criou duplicata
        self.assertEqual(wo.checklist_items.count(), 1)

    def test_form_deletes_items_removed_from_json(self):
        wo = WorkOrder.objects.create(
            empresa=self.empresa, title="OS", lead=self.lead,
            priority="medium",
        )
        keep = WorkOrderChecklist.objects.create(
            work_order=wo, description="Manter", order=0,
        )
        WorkOrderChecklist.objects.create(
            work_order=wo, description="Remover", order=1,
        )
        # JSON envia apenas o que sobrevive
        items = [{"id": keep.pk, "description": "Manter"}]
        form = WorkOrderForm(
            data=self._base_data(checklist_json=json.dumps(items)),
            instance=wo, empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(wo.checklist_items.count(), 1)
        self.assertEqual(wo.checklist_items.first().pk, keep.pk)

    def test_form_reorders_items(self):
        wo = WorkOrder.objects.create(
            empresa=self.empresa, title="OS", lead=self.lead,
            priority="medium",
        )
        a = WorkOrderChecklist.objects.create(
            work_order=wo, description="A", order=0,
        )
        b = WorkOrderChecklist.objects.create(
            work_order=wo, description="B", order=1,
        )
        c = WorkOrderChecklist.objects.create(
            work_order=wo, description="C", order=2,
        )
        # User inverteu: C, A, B
        items = [
            {"id": c.pk, "description": "C"},
            {"id": a.pk, "description": "A"},
            {"id": b.pk, "description": "B"},
        ]
        form = WorkOrderForm(
            data=self._base_data(checklist_json=json.dumps(items)),
            instance=wo, empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        final = list(
            wo.checklist_items.order_by("order").values_list("description", flat=True)
        )
        self.assertEqual(final, ["C", "A", "B"])

    def test_empty_description_items_are_ignored(self):
        items = [
            {"description": "Real"},
            {"description": ""},
            {"description": "   "},
            {"description": "Outro real"},
        ]
        form = WorkOrderForm(
            data=self._base_data(checklist_json=json.dumps(items)),
            empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.instance.empresa = self.empresa
        wo = form.save()
        self.assertEqual(wo.checklist_items.count(), 2)
        descs = list(wo.checklist_items.values_list("description", flat=True))
        self.assertEqual(descs, ["Real", "Outro real"])

    def test_malformed_json_is_rejected(self):
        form = WorkOrderForm(
            data=self._base_data(checklist_json="isso nao é json"),
            empresa=self.empresa,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("checklist_json", form.errors)

    def test_non_list_json_is_rejected(self):
        form = WorkOrderForm(
            data=self._base_data(checklist_json='{"description": "single"}'),
            empresa=self.empresa,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("checklist_json", form.errors)

    def test_initial_prepopulates_existing_items(self):
        """Editar uma OS deve mostrar os items existentes no form."""
        wo = WorkOrder.objects.create(
            empresa=self.empresa, title="OS", lead=self.lead,
            priority="medium",
        )
        WorkOrderChecklist.objects.create(
            work_order=wo, description="Item 1", is_completed=False, order=0,
        )
        WorkOrderChecklist.objects.create(
            work_order=wo, description="Item 2", is_completed=True, order=1,
        )
        form = WorkOrderForm(instance=wo, empresa=self.empresa)
        initial = form.initial.get("checklist_json")
        self.assertIsNotNone(initial)
        parsed = json.loads(initial)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["description"], "Item 1")
        self.assertEqual(parsed[0]["is_completed"], False)
        self.assertEqual(parsed[1]["description"], "Item 2")
        self.assertEqual(parsed[1]["is_completed"], True)


class WorkOrderUpdateViewChecklistTests(TestCase):
    """Smoke end-to-end: POST no UpdateView cria items de checklist."""

    def setUp(self):
        self.empresa = create_test_empresa(slug="rv09-view")
        self.user = create_test_user("u@t.com", "U", self.empresa)
        self.lead = _make_lead(self.empresa)
        self.wo = WorkOrder.objects.create(
            empresa=self.empresa, title="OS Edit", lead=self.lead,
            priority="medium",
        )
        self.client.force_login(self.user)

    def test_update_view_creates_checklist_items(self):
        items = [
            {"description": "Tarefa 1"},
            {"description": "Tarefa 2"},
        ]
        response = self.client.post(
            reverse("operations:work_order_update", args=[self.wo.pk]),
            data={
                "title": "OS Editada",
                "lead": self.lead.pk,
                "priority": "high",
                "description": "Nova desc",
                "checklist_json": json.dumps(items),
                "cloud_storage_links_json": "",
            },
        )
        # Redireciona pra list após sucesso
        self.assertIn(response.status_code, (302, 200))
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.checklist_items.count(), 2)
        descs = set(
            self.wo.checklist_items.values_list("description", flat=True)
        )
        self.assertEqual(descs, {"Tarefa 1", "Tarefa 2"})
