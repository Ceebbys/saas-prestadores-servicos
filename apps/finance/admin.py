from django.contrib import admin

from .models import FinancialCategory, FinancialEntry


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
