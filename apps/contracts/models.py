from decimal import Decimal

from django.db import models
from django.urls import reverse

from apps.core.models import SoftDeletableModel, TenantOwnedModel, TimestampedModel
from apps.core.utils import generate_number


def _contract_header_image_path(instance, filename):
    """Path isolado por empresa para imagens de cabeçalho de contrato."""
    empresa_id = getattr(instance, "empresa_id", None) or "shared"
    return f"contracts/headers/{empresa_id}/{filename}"


def _contract_footer_image_path(instance, filename):
    empresa_id = getattr(instance, "empresa_id", None) or "shared"
    return f"contracts/footers/{empresa_id}/{filename}"


class ContractTemplate(TenantOwnedModel):
    """Template reutilizável para contratos (RV05 #11 — padronizado com proposta)."""

    name = models.CharField("Nome", max_length=255)
    content = models.TextField(
        "Conteúdo (legado)",
        blank=True,
        help_text="Campo legado. Use 'body' (rich-text) para novos templates.",
    )
    is_default = models.BooleanField("Padrão", default=False)

    # RV05 #11 — Cabeçalho/rodapé/rich
    header_image = models.ImageField(
        "Imagem do cabeçalho",
        upload_to=_contract_header_image_path,
        blank=True, null=True,
        help_text="PNG, JPG ou WEBP. Máx. 2MB.",
    )
    header_content = models.TextField("Cabeçalho (texto rich)", blank=True)
    introduction = models.TextField("Introdução padrão", blank=True)
    body = models.TextField(
        "Corpo do contrato (rich)",
        blank=True,
        help_text="Substitui o campo 'content' legado.",
    )
    terms = models.TextField("Termos padrão", blank=True)
    footer_image = models.ImageField(
        "Imagem do rodapé",
        upload_to=_contract_footer_image_path,
        blank=True, null=True,
    )
    footer_content = models.TextField("Rodapé (texto rich)", blank=True)

    class Meta:
        verbose_name = "Template de Contrato"
        verbose_name_plural = "Templates de Contrato"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.is_default:
            ContractTemplate.objects.filter(
                empresa=self.empresa, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class Contract(SoftDeletableModel, TenantOwnedModel):
    """Contrato firmado com um lead/cliente.

    Soft-delete: Contract.objects esconde cancelados/excluídos; all_objects
    inclui tudo (lixeira). Lead.contract = PROTECT preserva a relação
    documental ao tentar excluir o Lead.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        SENT = "sent", "Enviado"
        SIGNED = "signed", "Assinado"
        ACTIVE = "active", "Ativo"
        COMPLETED = "completed", "Concluído"
        CANCELLED = "cancelled", "Cancelado"

    number = models.CharField("Número", max_length=50, db_index=True)
    proposal = models.ForeignKey(
        "proposals.Proposal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts",
        verbose_name="Proposta",
    )
    lead = models.ForeignKey(
        "crm.Lead",
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name="Lead",
        help_text=(
            "Lead vinculado. PROTECT impede exclusão acidental de leads com "
            "contratos: contrato assinado preserva a relação documental para "
            "fins fiscais/LGPD. Para excluir, finalize ou exclua o contrato primeiro."
        ),
    )
    template = models.ForeignKey(
        ContractTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts",
        verbose_name="Template",
    )
    title = models.CharField("Título", max_length=255)
    # Campo legado RV03/RV04 — preserva conteúdo de contratos antigos.
    # Drop planejado para RV06 após migration RunPython sanitizar e copiar
    # para `body`. Templates antigos ainda podem renderizar via fallback.
    content = models.TextField(
        "Conteúdo (legado)",
        blank=True,
        help_text="Campo legado. Use 'body' (rich-text) para novos contratos.",
    )

    # RV05 #11 — Padronização com Proposta.
    header_image = models.ImageField(
        "Imagem do cabeçalho",
        upload_to=_contract_header_image_path,
        blank=True, null=True,
        help_text="PNG, JPG ou WEBP. Máx. 2MB. Se vazio, herda do template.",
    )
    header_content = models.TextField("Cabeçalho (texto rich)", blank=True)
    introduction = models.TextField("Introdução", blank=True)
    body = models.TextField(
        "Corpo do contrato (rich)",
        blank=True,
        help_text="Substitui o campo 'content' legado. Aceita HTML formatado.",
    )
    terms = models.TextField("Termos e condições", blank=True)
    footer_image = models.ImageField(
        "Imagem do rodapé",
        upload_to=_contract_footer_image_path,
        blank=True, null=True,
    )
    footer_content = models.TextField("Rodapé (texto rich)", blank=True)

    value = models.DecimalField(
        "Valor", max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    status = models.CharField(
        "Status",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    start_date = models.DateField("Data de Início", null=True, blank=True)
    end_date = models.DateField("Data de Término", null=True, blank=True)
    signed_at = models.DateTimeField("Assinado em", null=True, blank=True)
    notes = models.TextField("Observações", blank=True)

    class Meta:
        verbose_name = "Contrato"
        verbose_name_plural = "Contratos"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.number} - {self.title}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_number(self.empresa, "CONT", Contract)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("contracts:detail", kwargs={"pk": self.pk})


class ContractStatusHistory(TimestampedModel):
    """Registro auditável de cada alteração de status de um contrato.

    Análogo a `ProposalStatusHistory`. Reforça a justificativa LGPD/fiscal
    da PROTECT em `Contract.lead`: cada mudança de status fica registrada
    com autor e momento, garantindo trilha completa.
    """

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="status_history",
        verbose_name="Contrato",
    )
    from_status = models.CharField(
        "De",
        max_length=20,
        choices=Contract.Status.choices,
        blank=True,
    )
    to_status = models.CharField(
        "Para",
        max_length=20,
        choices=Contract.Status.choices,
    )
    changed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contract_status_changes",
        verbose_name="Alterado por",
    )
    note = models.TextField("Observação", blank=True)

    class Meta:
        verbose_name = "Histórico de Status do Contrato"
        verbose_name_plural = "Históricos de Status dos Contratos"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["contract", "-created_at"]),
        ]

    def __str__(self):
        return (
            f"{self.contract.number}: "
            f"{self.from_status or '∅'} → {self.to_status}"
        )
