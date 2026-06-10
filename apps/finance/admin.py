from django.contrib import admin

from .models import (
    BankConnection,
    FinancialCategory,
    FinancialEntry,
    ImportedTransaction,
)


@admin.register(FinancialCategory)
class FinancialCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "empresa", "is_active")
    list_filter = ("type", "is_active")
    search_fields = ("name",)


@admin.register(FinancialEntry)
class FinancialEntryAdmin(admin.ModelAdmin):
    list_display = (
        "description",
        "type",
        "amount",
        "category",
        "date",
        "status",
        "empresa",
    )
    list_filter = ("type", "status", "category")
    search_fields = ("description",)
    date_hierarchy = "date"


@admin.register(BankConnection)
class BankConnectionAdmin(admin.ModelAdmin):
    list_display = ("provider", "status", "empresa", "bank_account", "last_synced_at")
    list_filter = ("provider", "status")


@admin.register(ImportedTransaction)
class ImportedTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "date", "direction", "amount", "classification_status", "empresa",
    )
    list_filter = ("classification_status", "direction")
    search_fields = ("description", "external_id")
    date_hierarchy = "date"
