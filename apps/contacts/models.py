"""Contato — central de contatos reutilizável (estilo Google Contatos).

Os dados de cliente vivem aqui (não mais dentro do Lead). Um mesmo Contato
pode gerar múltiplos Leads/Oportunidades. Unicidade é por (empresa, documento)
para preservar o isolamento multi-tenant — o mesmo CPF/CNPJ pode existir em
empresas diferentes.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Index, Q, UniqueConstraint

from apps.core.models import TenantOwnedModel
from apps.core.validators import normalize_document, validate_cpf_or_cnpj


class Contato(TenantOwnedModel):
    class Source(models.TextChoices):
        SITE = "site", "Site"
        INDICACAO = "indicacao", "Indicação"
        GOOGLE = "google", "Google"
        INSTAGRAM = "instagram", "Instagram"
        WHATSAPP = "whatsapp", "WhatsApp"
        TELEFONE = "telefone", "Telefone"
        CHATBOT = "chatbot", "Chatbot"
        IMPORT = "import", "Importação"
        OUTRO = "outro", "Outro"

    name = models.CharField("Nome", max_length=255)
    cpf_cnpj = models.CharField(
        "CPF/CNPJ",
        max_length=18,
        blank=True,
        validators=[validate_cpf_or_cnpj],
        help_text="Pode ser informado com ou sem máscara.",
    )
    cpf_cnpj_normalized = models.CharField(
        max_length=14,
        blank=True,
        editable=False,
        db_index=True,
    )
    phone = models.CharField("Telefone", max_length=20, blank=True)
    whatsapp = models.CharField("WhatsApp", max_length=20, blank=True)
    email = models.EmailField("E-mail", blank=True)
    company = models.CharField("Empresa do contato", max_length=255, blank=True)
    notes = models.TextField("Observações", blank=True)
    source = models.CharField(
        "Origem",
        max_length=20,
        choices=Source.choices,
        blank=True,
    )
    is_active = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Contato"
        verbose_name_plural = "Contatos"
        ordering = ["name"]
        constraints = [
            UniqueConstraint(
                fields=["empresa", "cpf_cnpj_normalized"],
                condition=~Q(cpf_cnpj_normalized=""),
                name="contacts_unique_doc_per_empresa",
            ),
        ]
        indexes = [
            Index(fields=["empresa", "name"]),
            Index(fields=["empresa", "phone"]),
            Index(fields=["empresa", "email"]),
        ]

    def __str__(self):
        if self.cpf_cnpj_normalized:
            return f"{self.name} ({self.cpf_cnpj})"
        return self.name

    def save(self, *args, **kwargs):
        # Always derive normalized doc from cpf_cnpj before saving
        self.cpf_cnpj_normalized = normalize_document(self.cpf_cnpj or "")
        super().save(*args, **kwargs)

    @property
    def is_pessoa_juridica(self) -> bool:
        return len(self.cpf_cnpj_normalized) == 14

    @property
    def is_pessoa_fisica(self) -> bool:
        return len(self.cpf_cnpj_normalized) == 11

    @property
    def whatsapp_or_phone(self) -> str:
        return self.whatsapp or self.phone
