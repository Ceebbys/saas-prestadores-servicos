from django.contrib import admin

from .models import Lead, LeadContact, Opportunity, Pipeline, PipelineStage


class PipelineStageInline(admin.TabularInline):
    model = PipelineStage
    extra = 1
    ordering = ["order"]


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = (
        "name", "email", "company", "source", "pipeline_stage", "assigned_to", "created_at",
    )
    list_filter = ("pipeline_stage", "source", "empresa")
    search_fields = ("name", "email", "company", "phone", "cpf", "cnpj")
    list_select_related = ("assigned_to", "empresa", "pipeline_stage")


@admin.register(LeadContact)
class LeadContactAdmin(admin.ModelAdmin):
    list_display = ("lead", "channel", "contacted_at", "user", "empresa")
    list_filter = ("channel", "empresa")
    search_fields = ("lead__name", "note")
    list_select_related = ("lead", "user", "empresa")
    date_hierarchy = "contacted_at"


@admin.register(Pipeline)
class PipelineAdmin(admin.ModelAdmin):
    list_display = ("name", "empresa", "is_default", "created_at")
    list_filter = ("is_default", "empresa")
    search_fields = ("name",)
    inlines = [PipelineStageInline]


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "lead",
        "pipeline",
        "current_stage",
        "value",
        "probability",
        "priority",
        "assigned_to",
        "created_at",
    )
    list_filter = ("priority", "pipeline", "current_stage", "empresa")
    search_fields = ("title", "lead__name", "notes")
    list_select_related = ("lead", "pipeline", "current_stage", "assigned_to", "empresa")
