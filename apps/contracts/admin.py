from django.contrib import admin

from apps.contracts.models import Contract, ContractTemplate


@admin.register(ContractTemplate)
class ContractTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "empresa", "is_default", "created_at"]
    list_filter = ["is_default", "empresa"]
    search_fields = ["name"]


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "title",
        "lead",
        "status",
        "value",
        "start_date",
        "end_date",
        "created_at",
    ]
    list_filter = ["status", "empresa"]
    search_fields = ["number", "title"]
    readonly_fields = ["number"]
