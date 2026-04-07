from django.db import models

from apps.core.models import TenantOwnedModel


class BankAccount(TenantOwnedModel):
    """Conta bancária da empresa (PJ ou PF)."""

    class AccountType(models.TextChoices):
        CHECKING = "checking", "Conta Corrente"
        SAVINGS = "savings", "Poupança"
        PAYMENT = "payment", "Conta de Pagamento"

    class PersonType(models.TextChoices):
        PJ = "pj", "Pessoa Jurídica"
        PF = "pf", "Pessoa Física"

    name = models.CharField("Apelido", max_length=100, help_text="Ex: Conta PJ Itaú")
    bank_name = models.CharField("Banco", max_length=100)
    bank_code = models.CharField("Código do banco", max_length=10, blank=True)
    agency = models.CharField("Agência", max_length=20, blank=True)
    account_number = models.CharField("Número da conta", max_length=30, blank=True)
    account_type = models.CharField(
        "Tipo de conta",
        max_length=20,
        choices=AccountType.choices,
        default=AccountType.CHECKING,
    )
    person_type = models.CharField(
        "Tipo de pessoa",
        max_length=5,
        choices=PersonType.choices,
        default=PersonType.PJ,
    )
    holder_name = models.CharField("Titular", max_length=200, blank=True)
    holder_document = models.CharField(
        "CPF/CNPJ do titular", max_length=20, blank=True
    )
    pix_key = models.CharField(
        "Chave Pix", max_length=200, blank=True,
        help_text="CPF, CNPJ, e-mail, telefone ou chave aleatória",
    )
    is_default = models.BooleanField(
        "Conta padrão", default=False,
        help_text="Conta usada como padrão em novos lançamentos",
    )
    is_active = models.BooleanField("Ativa", default=True)
    notes = models.TextField("Observações", blank=True)

    class Meta:
        verbose_name = "Conta Bancária"
        verbose_name_plural = "Contas Bancárias"
        ordering = ["-is_default", "name"]

    def __str__(self):
        parts = [self.name]
        if self.bank_name:
            parts.append(f"({self.bank_name})")
        return " ".join(parts)

    def save(self, *args, **kwargs):
        # Garante apenas uma conta padrão por empresa
        if self.is_default:
            BankAccount.objects.filter(
                empresa=self.empresa, is_default=True,
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


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
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entries",
        verbose_name="Conta Bancária",
    )
    payment_ref = models.CharField(
        "Referência de pagamento",
        max_length=200,
        blank=True,
        help_text="Código de barras, ID Pix, ou referência externa",
    )
    notes = models.TextField("Observações", blank=True)
    auto_generated = models.BooleanField(
        "Gerado automaticamente",
        default=False,
        help_text=(
            "Indica que este lançamento foi criado automaticamente a partir de "
            "uma proposta/contrato. Pode ser editado manualmente."
        ),
    )

    class Meta:
        verbose_name = "Lançamento Financeiro"
        verbose_name_plural = "Lançamentos"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.description} - R$ {self.amount}"
