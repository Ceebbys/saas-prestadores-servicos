from django.contrib import admin

from .models import Lead, Opportunity, Pipeline, PipelineStage


class PipelineStageInline(admin.TabularInline):
    model = PipelineStage
    extra = 1
    ordering = ["order"]


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "company", "source", "status", "assigned_to", "created_at")
    list_filter = ("status", "source", "empresa")
    search_fields = ("name", "email", "company", "phone")
    list_select_related = ("assigned_to", "empresa")


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
