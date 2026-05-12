"""RV05-F — Sanitiza Contract.content legado e copia para body se body vazio.

Garante que contratos antigos (criados antes da migração para campos rich)
tenham seu conteúdo passado pelo sanitizer HTML e copiado para `body`,
permitindo que o template print renderize com `|safe` sem risco de XSS.

Idempotente: roda múltiplas vezes sem efeito colateral. Reversível: o reverse
no-op preserva os dados (não desfaz a cópia).

Aplicada também em ContractTemplate por simetria.
"""
from html import escape as html_escape

from django.db import migrations


def _sanitize_html_inplace(text: str) -> str:
    """Aplica nh3 via sanitizer compartilhado, com fallback para escape simples."""
    if not text:
        return ""
    try:
        from apps.core.document_render.sanitizer import sanitize_rich_html
        return sanitize_rich_html(text)
    except Exception:
        # Defensive: se sanitizer falhar (lib não disponível em CI antiga),
        # ao menos escapa < > & para evitar render direto de HTML cru.
        return html_escape(text, quote=True)


def sanitize_and_copy_legacy_content(apps_registry, schema_editor):
    Contract = apps_registry.get_model("contracts", "Contract")
    ContractTemplate = apps_registry.get_model("contracts", "ContractTemplate")

    # Contratos: copia content → body sanitizado se body vazio.
    # Usa update via individual save para preservar updated_at e qualquer signal.
    for c in Contract.objects.exclude(content="").filter(body=""):
        sanitized = _sanitize_html_inplace(c.content)
        if not sanitized:
            continue
        c.body = sanitized
        c.save(update_fields=["body", "updated_at"])

    # ContractTemplate: mesma lógica
    for t in ContractTemplate.objects.exclude(content="").filter(body=""):
        sanitized = _sanitize_html_inplace(t.content)
        if not sanitized:
            continue
        t.body = sanitized
        t.save(update_fields=["body", "updated_at"])


def reverse_noop(apps_registry, schema_editor):
    """Reverse intencionalmente no-op: não apagamos body porque o content
    legado ainda existe lado-a-lado. Operação é idempotente forward."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("contracts", "0004_contract_status_history"),
    ]

    operations = [
        migrations.RunPython(sanitize_and_copy_legacy_content, reverse_noop),
    ]
