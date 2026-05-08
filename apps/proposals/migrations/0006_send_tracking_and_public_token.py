"""Adiciona tracking de envio (email/WhatsApp) e public_token para visualização pública.

Estratégia para o token único: cria nullable primeiro, popula com UUIDs distintos
via RunPython, e só depois adiciona o constraint unique=True.
"""
import uuid

from django.db import migrations, models


def _populate_public_tokens(apps, schema_editor):
    Proposal = apps.get_model("proposals", "Proposal")
    for proposal in Proposal.objects.filter(public_token__isnull=True):
        proposal.public_token = uuid.uuid4()
        proposal.save(update_fields=["public_token"])


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("proposals", "0005_status_history_and_cancelled"),
    ]

    operations = [
        migrations.AddField(
            model_name="proposal",
            name="last_email_sent_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Último envio por e-mail"
            ),
        ),
        migrations.AddField(
            model_name="proposal",
            name="last_whatsapp_sent_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Último envio por WhatsApp"
            ),
        ),
        # 1) Adiciona o campo nullable, sem unique
        migrations.AddField(
            model_name="proposal",
            name="public_token",
            field=models.UUIDField(
                db_index=True,
                editable=False,
                null=True,
                verbose_name="Token público",
            ),
        ),
        # 2) Popula UUIDs distintos para rows existentes
        migrations.RunPython(_populate_public_tokens, _noop_reverse),
        # 3) Aplica unique + default + not null
        migrations.AlterField(
            model_name="proposal",
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
            model_name="proposal",
            name="viewed_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Visualizada em"
            ),
        ),
    ]
