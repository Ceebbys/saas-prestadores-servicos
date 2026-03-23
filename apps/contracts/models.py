from decimal import Decimal

from django.db import models
from django.urls import reverse

from apps.core.models import TenantOwnedModel
from apps.core.utils import generate_number


class ContractTemplate(TenantOwnedModel):
    """Template reutilizável para contratos."""

    name = models.CharField("Nome", max_length=255)
    content = models.TextField("Conteúdo")
    is_default = models.BooleanField("Padrão", default=False)

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


class Contract(TenantOwnedModel):
    """Contrato firmado com um lead/cliente."""

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
        on_delete=models.CASCADE,
        related_name="contracts",
        verbose_name="Lead",
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
    content = models.TextField("Conteúdo")
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
