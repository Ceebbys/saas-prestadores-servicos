"""RV06 — Adiciona public_token + tracking de envio em Contract.

Mesmo padrão de 3 steps de proposals.0006 (nullable → populate UUIDs → unique).
"""
import uuid

from django.db import migrations, models


def _populate_public_tokens(apps, schema_editor):
    Contract = apps.get_model("contracts", "Contract")
    for contract in Contract.objects.filter(public_token__isnull=True):
        contract.public_token = uuid.uuid4()
        contract.save(update_fields=["public_token"])


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("contracts", "0005_sanitize_legacy_content"),
    ]

    operations = [
        # 1) nullable
        migrations.AddField(
            model_name="contract",
            name="public_token",
            field=models.UUIDField(
                db_index=True,
                editable=False,
                null=True,
                verbose_name="Token público",
            ),
        ),
        # 2) popular UUIDs
        migrations.RunPython(_populate_public_tokens, _noop_reverse),
        # 3) unique + default + not null
        migrations.AlterField(
            model_name="contract",
            name="public_token",
            field=models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                editable=False,
                unique=True,
                verbose_name="Token público",
            ),
        ),
        migrations.AddField(
            model_name="contract",
            name="last_whatsapp_sent_at",
            field=models.DateTimeField(
                blank=True, editable=False, null=True,
                verbose_name="Último envio WhatsApp",
            ),
        ),
        migrations.AddField(
            model_name="contract",
            name="sent_at",
            field=models.DateTimeField(
                blank=True, editable=False, null=True,
                help_text="Timestamp do primeiro envio (qualquer canal).",
                verbose_name="Enviado em",
            ),
        ),
    ]
