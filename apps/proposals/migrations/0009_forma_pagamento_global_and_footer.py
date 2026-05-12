"""RV05 FASE 4 — Múltiplas formas de pagamento + rodapé na proposta.

Seed das 6 formas padrão (PIX, Cartão Crédito/Débito, Dinheiro, Transferência, Boleto)
e backfill: para cada proposta com `payment_method` legado preenchido, vincula
ao FormaPagamento correspondente via M2M. Campo legado mantido por uma release.
"""
import apps.proposals.models
from django.db import migrations, models


SEED_FORMAS = [
    ("pix", "Pix", 1),
    ("cartao_credito", "Cartão de Crédito", 2),
    ("cartao_debito", "Cartão de Débito", 3),
    ("dinheiro", "Dinheiro", 4),
    ("transferencia", "Transferência", 5),
    ("boleto", "Boleto", 6),
]


def seed_and_backfill(apps_registry, schema_editor):
    FormaPagamento = apps_registry.get_model("proposals", "FormaPagamento")
    Proposal = apps_registry.get_model("proposals", "Proposal")

    # Seed 6 formas globais
    slug_to_obj = {}
    for slug, nome, ordem in SEED_FORMAS:
        obj, _ = FormaPagamento.objects.update_or_create(
            slug=slug,
            defaults={"nome": nome, "ordem": ordem, "is_active": True},
        )
        slug_to_obj[slug] = obj

    # Backfill: copia legacy payment_method → M2M correspondente.
    # Aceita também proposals soft-deleted (Proposal.all_objects via raw queryset
    # — no migration framework, model histórico não tem manager custom).
    for p in Proposal.objects.exclude(payment_method=""):
        if p.payment_method in slug_to_obj:
            p.payment_methods.add(slug_to_obj[p.payment_method])


def remove_seed(apps_registry, schema_editor):
    # Reverse: remove só os slugs seedados, sem tocar outros que o usuário
    # possa ter criado depois.
    FormaPagamento = apps_registry.get_model("proposals", "FormaPagamento")
    FormaPagamento.objects.filter(slug__in=[s for s, _, _ in SEED_FORMAS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('proposals', '0008_proposal_soft_delete'),
    ]

    operations = [
        migrations.CreateModel(
            name='FormaPagamento',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(max_length=40, unique=True, verbose_name='Slug')),
                ('nome', models.CharField(max_length=80, verbose_name='Nome')),
                ('ordem', models.PositiveIntegerField(default=0, verbose_name='Ordem')),
                ('is_active', models.BooleanField(default=True, verbose_name='Ativa')),
            ],
            options={
                'verbose_name': 'Forma de Pagamento',
                'verbose_name_plural': 'Formas de Pagamento',
                'ordering': ['ordem', 'nome'],
            },
        ),
        migrations.AddField(
            model_name='proposal',
            name='footer_content',
            field=models.TextField(blank=True, help_text='Texto rico — observações finais, contatos, info legais.', verbose_name='Conteúdo do rodapé'),
        ),
        migrations.AddField(
            model_name='proposal',
            name='footer_image',
            field=models.ImageField(blank=True, help_text='PNG, JPG ou WEBP. Máx. 2MB.', null=True, upload_to=apps.proposals.models._proposal_footer_image_path, verbose_name='Imagem do rodapé (logo/identidade)'),
        ),
        migrations.AlterField(
            model_name='proposal',
            name='payment_method',
            field=models.CharField(blank=True, choices=[('pix', 'Pix'), ('boleto', 'Boleto'), ('cartao_credito', 'Cartão de Crédito'), ('cartao_debito', 'Cartão de Débito'), ('transferencia', 'Transferência'), ('dinheiro', 'Dinheiro'), ('outro', 'Outro')], max_length=50, verbose_name='Forma de Pagamento (legado)'),
        ),
        migrations.AddField(
            model_name='proposal',
            name='payment_methods',
            field=models.ManyToManyField(blank=True, related_name='proposals', to='proposals.FormaPagamento', verbose_name='Formas de pagamento'),
        ),
        # Seed + backfill
        migrations.RunPython(seed_and_backfill, remove_seed),
    ]
