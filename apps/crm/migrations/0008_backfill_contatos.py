"""Cria Contatos a partir dos Leads existentes que possuem CPF ou CNPJ.

Decisão de produto: Leads sem documento ficam com lead.contato = None.
A vinculação manual é feita pela UI quando o usuário desejar.

A migração é idempotente — pode rodar duas vezes sem duplicar contatos.
"""

import re

from django.db import migrations


def _only_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def forwards(apps, schema_editor):
    Lead = apps.get_model("crm", "Lead")
    Contato = apps.get_model("contacts", "Contato")

    qs = Lead.objects.exclude(cpf="", cnpj="").filter(contato__isnull=True)
    created = 0
    reused = 0
    skipped = 0

    for lead in qs:
        document = (lead.cpf or "").strip() or (lead.cnpj or "").strip()
        digits = _only_digits(document)
        if not digits or len(digits) not in (11, 14):
            skipped += 1
            continue

        existing = Contato.objects.filter(
            empresa_id=lead.empresa_id,
            cpf_cnpj_normalized=digits,
        ).first()

        if existing:
            lead.contato_id = existing.pk
            lead.save(update_fields=["contato"])
            reused += 1
            continue

        contato = Contato.objects.create(
            empresa_id=lead.empresa_id,
            name=lead.name or "(sem nome)",
            cpf_cnpj=document,
            cpf_cnpj_normalized=digits,
            phone=lead.phone or "",
            email=lead.email or "",
            company=lead.company or "",
            source=lead.source or "",
            is_active=True,
        )
        lead.contato_id = contato.pk
        lead.save(update_fields=["contato"])
        created += 1

    print(
        f"[crm.0008] Contatos criados: {created} | reusados: {reused} | "
        f"leads ignorados (sem doc válido): {skipped}"
    )


def backwards(apps, schema_editor):
    """Apenas desfaz a vinculação. Não exclui contatos criados (preserva dados)."""
    Lead = apps.get_model("crm", "Lead")
    Lead.objects.update(contato=None)


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0007_lead_contato"),
        ("contacts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
