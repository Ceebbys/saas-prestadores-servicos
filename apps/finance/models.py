from django.db import models

from apps.core.models import TenantOwnedModel


class FinancialCategory(TenantOwnedModel):
    """Categoria financeira para classificação de lançamentos."""

    class Type(models.TextChoices):
        INCOME = "income", "Receita"
        EXPENSE = "expense", "Despesa"

    name = models.CharField("Nome", max_length=100)
    type = models.CharField(
        "Tipo",
        max_length=10,
        choices=Type.choices,
    )
    is_active = models.BooleanField("Ativa", default=True)

    class Meta:
        verbose_name = "Categoria Financeira"
        verbose_name_plural = "Categorias Financeiras"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


class FinancialEntry(TenantOwnedModel):
    """Lançamento financeiro (receita ou despesa)."""

    class Type(models.TextChoices):
        INCOME = "income", "Receita"
        EXPENSE = "expense", "Despesa"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        PAID = "paid", "Pago"
        OVERDUE = "overdue", "Vencido"
        CANCELLED = "cancelled", "Cancelado"

    type = models.CharField(
        "Tipo",
        max_length=10,
        choices=Type.choices,
    )
    description = models.CharField("Descrição", max_length=500)
    amount = models.DecimalField("Valor", max_digits=12, decimal_places=2)
    category = models.ForeignKey(
        FinancialCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entries",
        verbose_name="Categoria",
    )
    date = models.DateField("Data de vencimento")
    paid_date = models.DateField("Data de pagamento", null=True, blank=True)
    status = models.CharField(
        "Status",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    related_proposal = models.ForeignKey(
        "proposals.Proposal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_entries",
        verbose_name="Proposta",
    )
    related_contract = models.ForeignKey(
        "contracts.Contract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_entries",
        verbose_name="Contrato",
    )
    related_work_order = models.ForeignKey(
        "operations.WorkOrder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_entries",
        verbose_name="Ordem de Serviço",
    )
    notes = models.TextField("Observações", blank=True)

    class Meta:
        verbose_name = "Lançamento Financeiro"
        verbose_name_plural = "Lançamentos"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.description} - R$ {self.amount}"
