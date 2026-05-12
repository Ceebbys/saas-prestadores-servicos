import uuid
from decimal import Decimal

from django.db import models
from django.urls import reverse

from apps.core.models import SoftDeletableModel, TenantOwnedModel, TimestampedModel
from apps.core.utils import generate_number


def _proposal_header_image_path(instance, filename):
    """Path por empresa: impede acesso cross-tenant via URL adivinhada."""
    empresa_id = getattr(instance, "empresa_id", None) or "shared"
    return f"proposals/headers/{empresa_id}/{filename}"


def _proposal_footer_image_path(instance, filename):
    """Path do rodapé (mesmo isolamento por empresa)."""
    empresa_id = getattr(instance, "empresa_id", None) or "shared"
    return f"proposals/footers/{empresa_id}/{filename}"


class FormaPagamento(models.Model):
    """Forma de pagamento — modelo GLOBAL (não tenant-owned).

    Catálogo universal: PIX, Cartão Crédito, Cartão Débito, Dinheiro,
    Transferência, Boleto. Permite múltipla seleção em Proposta via M2M.

    Não é TenantOwnedModel porque o catálogo é o mesmo para todas as
    empresas. Customização per-tenant (desativar uma forma, reordenar)
    fica como evolução futura via `FormaPagamentoEmpresa` se houver demanda.
    """

    slug = models.SlugField("Slug", unique=True, max_length=40)
    nome = models.CharField("Nome", max_length=80)
    ordem = models.PositiveIntegerField("Ordem", default=0)
    is_active = models.BooleanField("Ativa", default=True)

    class Meta:
        verbose_name = "Forma de Pagamento"
        verbose_name_plural = "Formas de Pagamento"
        ordering = ["ordem", "nome"]

    def __str__(self):
        return self.nome


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
    # RV05-F — Simetria com header. Permite cascata template→proposta.
    footer_image = models.ImageField(
        "Imagem do rodapé (logo/identidade)",
        upload_to=_proposal_footer_image_path,
        blank=True,
        null=True,
        help_text="PNG, JPG ou WEBP. Máx. 2MB.",
    )
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


class Proposal(SoftDeletableModel, TenantOwnedModel):
    """Proposta comercial enviada a um lead/oportunidade.

    Soft-delete via `SoftDeletableModel`:
    - `Proposal.objects` esconde excluídas
    - `Proposal.all_objects` mostra todas (lixeira)
    - `proposal.delete()` faz soft-delete
    - `proposal.hard_delete()` força exclusão real
    - `proposal.restore()` restaura
    """

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
    # Legado RV03 — único select de forma de pagamento. Mantido por uma
    # release (dual-read) — drop planejado para RV06. Migração 0010 popula
    # `payment_methods` a partir deste campo.
    payment_method = models.CharField(
        "Forma de Pagamento (legado)",
        max_length=50,
        choices=PaymentMethod.choices,
        blank=True,
    )
    # RV05 #5 — Múltiplas formas de pagamento simultâneas.
    payment_methods = models.ManyToManyField(
        FormaPagamento,
        blank=True,
        related_name="proposals",
        verbose_name="Formas de pagamento",
    )

    # RV05 #6 — Rodapé configurável.
    footer_image = models.ImageField(
        "Imagem do rodapé (logo/identidade)",
        upload_to=_proposal_footer_image_path,
        blank=True,
        null=True,
        help_text="PNG, JPG ou WEBP. Máx. 2MB.",
    )
    footer_content = models.TextField(
        "Conteúdo do rodapé",
        blank=True,
        help_text="Texto rico — observações finais, contatos, info legais.",
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
