"""RV08 (2.2) — Migra os itens de WorkOrderChecklist (checklist único da OS)
para a nova estrutura de múltiplos checklists (Checklist + ChecklistItem),
criando um checklist "Checklist" por Ordem de Serviço. Não destrói os dados
antigos (WorkOrderChecklist permanece como legado)."""
from collections import defaultdict

from django.db import migrations


def forwards(apps, schema_editor):
    WorkOrderChecklist = apps.get_model("operations", "WorkOrderChecklist")
    WorkOrder = apps.get_model("operations", "WorkOrder")
    Checklist = apps.get_model("checklists", "Checklist")
    ChecklistItem = apps.get_model("checklists", "ChecklistItem")
    ContentType = apps.get_model("contenttypes", "ContentType")

    wo_ct, _ = ContentType.objects.get_or_create(
        app_label="operations", model="workorder",
    )

    items_by_wo = defaultdict(list)
    for item in WorkOrderChecklist.objects.all():
        items_by_wo[item.work_order_id].append(item)

    for wo_id, items in items_by_wo.items():
        try:
            wo = WorkOrder.objects.get(pk=wo_id)
        except WorkOrder.DoesNotExist:
            continue
        # Idempotência: não duplica se já existe checklist para esta OS.
        if Checklist.objects.filter(
            content_type=wo_ct, object_id=wo_id,
        ).exists():
            continue
        checklist = Checklist.objects.create(
            empresa_id=wo.empresa_id,
            content_type=wo_ct,
            object_id=wo_id,
            name="Checklist",
            order=0,
        )
        for it in sorted(items, key=lambda x: (x.order, x.id)):
            ChecklistItem.objects.create(
                checklist=checklist,
                description=it.description,
                is_completed=it.is_completed,
                completed_at=it.completed_at,
                order=it.order,
            )


def backwards(apps, schema_editor):
    # Remove apenas os checklists gerados para WorkOrder (não toca o legado).
    Checklist = apps.get_model("checklists", "Checklist")
    ContentType = apps.get_model("contenttypes", "ContentType")
    wo_ct = ContentType.objects.filter(
        app_label="operations", model="workorder",
    ).first()
    if wo_ct:
        Checklist.objects.filter(content_type=wo_ct).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("checklists", "0001_initial"),
        ("operations", "0011_workorder_google_drive_folder_id"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
