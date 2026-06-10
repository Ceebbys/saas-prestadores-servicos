"""RV08 — Regressões do pente fino (OS checklist split-brain)."""
from django.test import TestCase
from django.urls import reverse

from apps.checklists.models import Checklist, ChecklistItem
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.operations.forms import WorkOrderForm
from apps.operations.models import WorkOrder, WorkOrderChecklist
from django.contrib.contenttypes.models import ContentType


class WorkOrderChecklistAuditTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv08-aud-ops")
        self.user = create_test_user("o@t.com", "O", self.empresa)
        self.client.force_login(self.user)

    def test_form_save_without_checklist_json_preserves_legacy_items(self):
        """H2 — salvar a OS sem o campo checklist_json não pode apagar itens
        legados (o editor saiu do form; sem guard, _sync apagaria tudo)."""
        wo = WorkOrder.objects.create(empresa=self.empresa, title="OS")
        WorkOrderChecklist.objects.create(work_order=wo, description="Item legado")
        form = WorkOrderForm(
            data={"title": "OS editada", "priority": "medium"},
            instance=wo, empresa=self.empresa,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        wo.refresh_from_db()
        self.assertEqual(wo.checklist_items.count(), 1)

    def test_pdf_template_renders_new_checklist_items(self):
        """H1 — o template do PDF da OS renderiza itens da estrutura NOVA."""
        from django.template.loader import render_to_string
        from django.utils import timezone

        wo = WorkOrder.objects.create(empresa=self.empresa, title="OS PDF")
        cl = Checklist.objects.create(
            empresa=self.empresa,
            content_type=ContentType.objects.get_for_model(WorkOrder),
            object_id=wo.pk, name="Execução",
        )
        item = ChecklistItem.objects.create(checklist=cl, description="Item novo do PDF")
        # A view monta checklist_items a partir de wo.checklists; simulamos o
        # mesmo contexto e confirmamos que o template renderiza o item novo.
        items = [it for c in wo.checklists.all() for it in c.items.all()]
        self.assertEqual(items, [item])
        html = render_to_string("operations/work_order_pdf.html", {
            "work_order": wo, "empresa": self.empresa,
            "checklist_items": items, "checklist_total": 1,
            "checklist_completed": 0, "now": timezone.now(),
        })
        self.assertIn("Item novo do PDF", html)
