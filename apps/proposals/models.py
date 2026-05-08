import uuid
from decimal import Decimal

from django.db import models
from django.urls import reverse

from apps.core.models import TenantOwnedModel, TimestampedModel
from apps.core.utils import generate_number


def _proposal_header_image_path(instance, filename):
    """Path por empresa: impede acesso cross-tenant via URL adivinhada."""
    empresa_id = getattr(instance, "empresa_id", None) or "shared"
    return f"proposals/headers/{empresa_id}/{filename}"


class ProposalTemplate(TenantOwnedModel):
    """Modelo de template reutilizável para propostas."""

    name = models.CharField("Nome", max_length=255)
    content = models.TextField("Conteúdo", blank=True)
    header_image = models.ImageField(
        "Imagem do cabeçalho (logo)",
        upload_to=_proposal_header_image_path,
        blank=True,
        null=True,
        help_text="PNG, JPG ou WEBP. Máx. 2MB.",
    )
    header_content = models.TextField("Conteúdo do Cabeçalho", blank=True)
    footer_content = models.TextField("Conteúdo do Rodapé", blank=True)
    introduction = models.TextField("Introdução padrão", blank=True)
    terms = models.TextField("Termos padrão", blank=True)
    default_payment_method = models.CharField(
        "Forma de pagamento padrão",
        max_length=50,
        blank=True,
    )
    default_is_installment = models.BooleanField(
        "Parcelado por padrão", default=False
    )
    default_installment_count = models.PositiveIntegerField(
        "Parcelas padrão", null=True, blank=True
    )
    is_default = models.BooleanField("Padrão", default=False)

    class Meta:
        verbose_name = "Template de Proposta"
        verbose_name_plural = "Templates de Proposta"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.is_default:
            ProposalTemplate.objects.filter(
                empresa=self.empresa, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class Proposal(TenantOwnedModel):
    """Proposta comercial enviada a um lead/oportunidade."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        SENT = "sent", "Enviada"
        VIEWED = "viewed", "Visualizada"
        ACCEPTED = "accepted", "Aceita"
        REJECTED = "rejected", "Rejeitada"
        EXPIRED = "expired", "Expirada"
        CANCELLED = "cancelled", "Cancelada"

    number = models.CharField("Número", max_length=50, db_index=True)
    opportunity = models.ForeignKey(
        "crm.Opportunity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposals",
        verbose_name="Oportunidade",
    )
    lead = models.ForeignKey(
        "crm.Lead",
        on_delete=models.CASCADE,
        related_name="proposals",
        verbose_name="Lead",
    )
    template = models.ForeignKey(
        ProposalTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposals",
        verbose_name="Template",
    )
    servico = models.ForeignKey(
        "operations.ServiceType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposals",
        verbose_name="Serviço Pré-Fixado",
    )
    title = models.CharField("Título", max_length=255)
    header_image = models.ImageField(
        "Imagem do cabeçalho (logo)",
        upload_to=_proposal_header_image_path,
        blank=True,
        null=True,
        help_text="PNG, JPG ou WEBP. Máx. 2MB. Se vazio, herda do template ou da empresa.",
    )
    use_template_header_image = models.BooleanField(
        "Usar imagem do template",
        default=True,
        help_text="Se ativo, herda imagem do template/empresa quando esta proposta não tem própria.",
    )
    introduction = models.TextField("Introdução", blank=True)
    body = models.TextField("Corpo da proposta", blank=True)
    terms = models.TextField("Termos e Condições", blank=True)
    status = models.CharField(
        "Status",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    subtotal = models.DecimalField(
        "Subtotal", max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    discount_percent = models.DecimalField(
        "Desconto (%)", max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        "Total", max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    valid_until = models.DateField("Válida até", null=True, blank=True)

    # Parcelamento
    class PaymentMethod(models.TextChoices):
        PIX = "pix", "Pix"
        BOLETO = "boleto", "Boleto"
        CARTAO_CREDITO = "cartao_credito", "Cartão de Crédito"
        CARTAO_DEBITO = "cartao_debito", "Cartão de Débito"
        TRANSFERENCIA = "transferencia", "Transferência"
        DINHEIRO = "dinheiro", "Dinheiro"
        OUTRO = "outro", "Outro"

    is_installment = models.BooleanField("Parcelado", default=False)
    installment_count = models.PositiveIntegerField(
        "Número de Parcelas", null=True, blank=True
    )
    payment_method = models.CharField(
        "Forma de Pagamento",
        max_length=50,
        choices=PaymentMethod.choices,
        blank=True,
    )

    sent_at = models.DateTimeField("Enviada em", null=True, blank=True)
    accepted_at = models.DateTimeField("Aceita em", null=True, blank=True)
    rejected_at = models.DateTimeField("Rejeitada em", null=True, blank=True)
    viewed_at = models.DateTimeField("Visualizada em", null=True, blank=True)
    last_email_sent_at = models.DateTimeField(
        "Último envio por e-mail", null=True, blank=True,
    )
    last_whatsapp_sent_at = models.DateTimeField(
        "Último envio por WhatsApp", null=True, blank=True,
    )

    # Token para visualização pública (envio por link). UUID4 indexado.
    public_token = models.UUIDField(
        "Token público",
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
    )

    class Meta:
        verbose_name = "Proposta"
        verbose_name_plural = "Propostas"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.number} - {self.title}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_number(self.empresa, "PROP", Proposal)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("proposals:detail", kwargs={"pk": self.pk})

    def recalculate_totals(self):
        """Recalcula subtotal e total com base nos itens e desconto."""
        self.subtotal = (
            self.items.aggregate(total=models.Sum("total"))["total"]
            or Decimal("0.00")
        )
        discount_amount = self.subtotal * (self.discount_percent / Decimal("100"))
        self.total = self.subtotal - discount_amount
        self.save(update_fields=["subtotal", "total"])


class ProposalItem(TimestampedModel):
    """Item individual de uma proposta."""

    proposal = models.ForeignKey(
        Proposal,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Proposta",
    )
    description = models.CharField("Descrição", max_length=500)
    details = models.TextField("Detalhes", blank=True)
    quantity = models.DecimalField(
        "Quantidade", max_digits=10, decimal_places=2, default=Decimal("1.00")
    )
    unit = models.CharField("Unidade", max_length=20, default="un")
    unit_price = models.DecimalField(
        "Preço Unitário", max_digits=12, decimal_places=2
    )
    total = models.DecimalField(
        "Total", max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    order = models.PositiveIntegerField("Ordem", default=0)

    class Meta:
        verbose_name = "Item da Proposta"
        verbose_name_plural = "Itens da Proposta"
        ordering = ["order"]

    def __str__(self):
        return self.description

    def save(self, *args, **kwargs):
        self.total = self.quantity * self.unit_price
        super().save(*args, **kwargs)


class ProposalStatusHistory(TimestampedModel):
    """Registro auditável de cada alteração de status de uma proposta."""

    proposal = models.ForeignKey(
        Proposal,
        on_delete=models.CASCADE,
        related_name="status_history",
        verbose_name="Proposta",
    )
    from_status = models.CharField(
        "De",
        max_length=20,
        choices=Proposal.Status.choices,
        blank=True,
    )
    to_status = models.CharField(
        "Para",
        max_length=20,
        choices=Proposal.Status.choices,
    )
    changed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposal_status_changes",
        verbose_name="Alterado por",
    )
    note = models.TextField("Observação", blank=True)

    class Meta:
        verbose_name = "Histórico de Status da Proposta"
        verbose_name_plural = "Históricos de Status das Propostas"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["proposal", "-created_at"]),
        ]

    def __str__(self):
        return (
            f"{self.proposal.number}: "
            f"{self.from_status or '∅'} → {self.to_status}"
        )


class ProposalTemplateItem(TimestampedModel):
    """Item padrão de um template de proposta, aplicado ao criar propostas."""

    template = models.ForeignKey(
        ProposalTemplate,
        on_delete=models.CASCADE,
        related_name="default_items",
        verbose_name="Template",
    )
    description = models.CharField("Descrição", max_length=500)
    details = models.TextField("Detalhes", blank=True)
    quantity = models.DecimalField(
        "Quantidade", max_digits=10, decimal_places=2, default=Decimal("1.00")
    )
    unit = models.CharField("Unidade", max_length=20, default="un")
    unit_price = models.DecimalField(
        "Preço Unitário", max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    order = models.PositiveIntegerField("Ordem", default=0)

    class Meta:
        verbose_name = "Item do Template"
        verbose_name_plural = "Itens do Template"
        ordering = ["order", "id"]

    def __str__(self):
        return self.description
