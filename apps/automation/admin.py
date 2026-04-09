from django.contrib import admin

from .models import AutomationLog


@admin.register(AutomationLog)
class AutomationLogAdmin(admin.ModelAdmin):
    list_display = (
        "action", "entity_type", "entity_id", "status",
        "source_entity_type", "source_entity_id", "empresa", "created_at",
    )
    list_filter = ("action", "status", "entity_type")
    search_fields = ("entity_type", "error_message")
    date_hierarchy = "created_at"
    readonly_fields = (
        "empresa", "entity_type", "entity_id", "action", "status",
        "source_entity_type", "source_entity_id", "metadata",
        "error_message", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
