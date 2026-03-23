from django.contrib import admin

from apps.proposals.models import Proposal, ProposalItem, ProposalTemplate


@admin.register(ProposalTemplate)
class ProposalTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "empresa", "is_default", "created_at"]
    list_filter = ["is_default", "empresa"]
    search_fields = ["name"]


class ProposalItemInline(admin.TabularInline):
    model = ProposalItem
    extra = 0
    fields = ["order", "description", "quantity", "unit", "unit_price", "total"]
    readonly_fields = ["total"]


@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "title",
        "lead",
        "status",
        "total",
        "valid_until",
        "created_at",
    ]
    list_filter = ["status", "empresa"]
    search_fields = ["number", "title"]
    readonly_fields = ["number", "subtotal", "total"]
    inlines = [ProposalItemInline]
