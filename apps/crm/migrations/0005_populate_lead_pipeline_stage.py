"""Mapeia Lead.status (string hardcoded) para Lead.pipeline_stage (FK).

Para cada empresa, usa o Pipeline default (ou cria um com as 7 stages padrão,
replicando a lógica de apps/accounts/views.py, caso ausente). O mapeamento:

    novo         -> stage order=0 (Prospecção)
    contatado    -> stage order=1 (Qualificação)
    qualificado  -> stage order=2 (Proposta)
    convertido   -> stage com is_won=True
    perdido      -> stage com is_lost=True

Fallback para status desconhecido: stage order=0 da pipeline default.
"""

from django.db import migrations


DEFAULT_STAGES = [
    ("Prospecção", 0, "#6366F1", False, False),
    ("Qualificação", 1, "#8B5CF6", False, False),
    ("Proposta", 2, "#F59E0B", False, False),
    ("Negociação", 3, "#F97316", False, False),
    ("Fechado/Ganho", 4, "#10B981", True, False),
    ("Fechado/Perdido", 5, "#EF4444", False, True),
    ("Pós-Venda", 6, "#06B6D4", False, False),
]


def _ensure_default_pipeline(Pipeline, PipelineStage, empresa):
    pipeline = Pipeline.objects.filter(empresa=empresa, is_default=True).first()
    if pipeline:
        return pipeline
    pipeline = Pipeline.objects.create(
        empresa=empresa,
        name="Pipeline Principal",
        is_default=True,
    )
    for name, order, color, is_won, is_lost in DEFAULT_STAGES:
        PipelineStage.objects.create(
            pipeline=pipeline,
            name=name,
            order=order,
            color=color,
            is_won=is_won,
            is_lost=is_lost,
        )
    return pipeline


def _resolve_stage(pipeline, status):
    stages = list(pipeline.stages.order_by("order"))
    if not stages:
        return None

    by_order = {s.order: s for s in stages}
    won_stage = next((s for s in stages if s.is_won), None)
    lost_stage = next((s for s in stages if s.is_lost), None)

    mapping = {
        "novo": by_order.get(0) or stages[0],
        "contatado": by_order.get(1) or by_order.get(0) or stages[0],
        "qualificado": by_order.get(2) or by_order.get(1) or stages[0],
        "convertido": won_stage or stages[-1],
        "perdido": lost_stage or stages[-1],
    }
    return mapping.get(status, stages[0])


def forwards(apps, schema_editor):
    Lead = apps.get_model("crm", "Lead")
    Pipeline = apps.get_model("crm", "Pipeline")
    PipelineStage = apps.get_model("crm", "PipelineStage")

    empresa_ids = Lead.objects.values_list("empresa_id", flat=True).distinct()
    for empresa_id in empresa_ids:
        Empresa = apps.get_model("accounts", "Empresa")
        empresa = Empresa.objects.get(pk=empresa_id)
        pipeline = _ensure_default_pipeline(Pipeline, PipelineStage, empresa)

        leads = Lead.objects.filter(empresa_id=empresa_id, pipeline_stage__isnull=True)
        for lead in leads:
            stage = _resolve_stage(pipeline, lead.status)
            if stage:
                lead.pipeline_stage_id = stage.id
                lead.save(update_fields=["pipeline_stage"])


def backwards(apps, schema_editor):
    """Reconstrói Lead.status a partir de pipeline_stage.

    Regra inversa: is_won -> convertido, is_lost -> perdido,
    order=0 -> novo, order=1 -> contatado, order=2 -> qualificado,
    demais -> novo (fallback seguro).
    """
    Lead = apps.get_model("crm", "Lead")
    leads = Lead.objects.exclude(pipeline_stage__isnull=True)
    for lead in leads:
        stage = lead.pipeline_stage
        if stage.is_won:
            lead.status = "convertido"
        elif stage.is_lost:
            lead.status = "perdido"
        elif stage.order == 1:
            lead.status = "contatado"
        elif stage.order == 2:
            lead.status = "qualificado"
        else:
            lead.status = "novo"
        lead.save(update_fields=["status"])


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0004_lead_cpf_cnpj_leadcontact_pipeline_stage"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
