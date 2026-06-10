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
    # RV06 — Vínculo direto com Lead quando negócio fecha SEM proposta/contrato
    # (ex.: fechamento via WhatsApp). Criado por signal quando Lead vai para
    # PipelineStage.is_won=True.
    related_lead = models.ForeignKey(
        "crm.Lead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="financial_entries",
        verbose_name="Lead",
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


# ---------------------------------------------------------------------------
# RV08 (6.1) — Open Finance: conexão bancária + movimentações importadas
# ---------------------------------------------------------------------------


class BankConnection(TenantOwnedModel):
    """Conexão de importação de movimentações bancárias (Open Finance).

    MVP: provider ``sandbox`` (gera movimentações demo) e ``manual`` (importação
    de extrato CSV/OFX). A interface é plugável — Pluggy/Belvo entram depois via
    settings, reusando o mesmo fluxo de classificação. Credenciais/tokens de um
    agregador real ficam criptografados (Fernet) em ``credentials_encrypted``.
    """

    class Provider(models.TextChoices):
        SANDBOX = "sandbox", "Sandbox (demonstração)"
        MANUAL = "manual", "Importação manual (CSV/OFX)"
        PLUGGY = "pluggy", "Pluggy"
        BELVO = "belvo", "Belvo"

    class Status(models.TextChoices):
        CONNECTED = "connected", "Conectado"
        DISCONNECTED = "disconnected", "Desconectado"
        ERROR = "error", "Erro"

    provider = models.CharField(
        "Provedor", max_length=20, choices=Provider.choices,
        default=Provider.MANUAL,
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="connections",
        verbose_name="Conta bancária",
    )
    status = models.CharField(
        "Status", max_length=20, choices=Status.choices, default=Status.CONNECTED,
    )
    credentials_encrypted = models.TextField(
        "Credenciais (cifradas)", blank=True,
        help_text="Token/credenciais do agregador, cifrados com Fernet.",
    )
    last_synced_at = models.DateTimeField("Última sincronização", null=True, blank=True)
    metadata = models.JSONField("Metadados", default=dict, blank=True)

    class Meta:
        verbose_name = "Conexão bancária (Open Finance)"
        verbose_name_plural = "Conexões bancárias (Open Finance)"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "provider"],
                name="uniq_bankconnection_empresa_provider",
            ),
        ]

    def __str__(self):
        return f"{self.get_provider_display()} ({self.get_status_display()})"


class ImportedTransaction(TenantOwnedModel):
    """Movimentação bancária importada, pendente de classificação.

    Idempotência por ``(empresa, external_id)``: re-importar o mesmo extrato não
    duplica. Ao classificar, gera um :class:`FinancialEntry` e fica vinculada a
    ele (``classified_entry``)."""

    class Direction(models.TextChoices):
        CREDIT = "credit", "Entrada"
        DEBIT = "debit", "Saída"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        CLASSIFIED = "classified", "Classificada"
        IGNORED = "ignored", "Ignorada"

    connection = models.ForeignKey(
        BankConnection,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="transactions",
        verbose_name="Conexão",
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="imported_transactions",
        verbose_name="Conta bancária",
    )
    external_id = models.CharField(
        "ID externo", max_length=200, db_index=True,
        help_text="Identificador da transação no banco/agregador (idempotência).",
    )
    date = models.DateField("Data")
    amount = models.DecimalField("Valor", max_digits=12, decimal_places=2)
    description = models.CharField("Descrição", max_length=500, blank=True)
    direction = models.CharField(
        "Sentido", max_length=10, choices=Direction.choices,
    )
    classification_status = models.CharField(
        "Classificação", max_length=12, choices=Status.choices,
        default=Status.PENDING,
    )
    classified_entry = models.ForeignKey(
        FinancialEntry,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="+",
        verbose_name="Lançamento gerado",
    )
    raw_payload = models.JSONField("Payload bruto", default=dict, blank=True)

    class Meta:
        verbose_name = "Movimentação importada"
        verbose_name_plural = "Movimentações importadas"
        ordering = ["-date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "external_id"],
                name="uniq_imported_txn_empresa_external_id",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "classification_status", "-date"]),
        ]

    def __str__(self):
        return f"{self.date} {self.get_direction_display()} R$ {self.amount}"

    @property
    def suggested_type(self) -> str:
        """Sugere receita/despesa a partir do sentido (crédito→receita)."""
        return (
            FinancialEntry.Type.INCOME
            if self.direction == self.Direction.CREDIT
            else FinancialEntry.Type.EXPENSE
        )
