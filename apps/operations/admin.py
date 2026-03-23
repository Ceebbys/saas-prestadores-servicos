from django.contrib import admin

from .models import (
    ChecklistItem,
    ChecklistTemplate,
    ServiceType,
    WorkOrder,
    WorkOrderChecklist,
)


@admin.register(ServiceType)
class ServiceTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "empresa", "estimated_duration_hours", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


class ChecklistItemInline(admin.TabularInline):
    model = ChecklistItem
    extra = 1
    ordering = ("order",)


@admin.register(ChecklistTemplate)
class ChecklistTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "empresa")
    search_fields = ("name",)
    inlines = [ChecklistItemInline]


class WorkOrderChecklistInline(admin.TabularInline):
    model = WorkOrderChecklist
    extra = 0
    ordering = ("order",)


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "title",
        "empresa",
        "status",
        "priority",
        "scheduled_date",
        "assigned_to",
    )
    list_filter = ("status", "priority")
    search_fields = ("number", "title")
    inlines = [WorkOrderChecklistInline]


@admin.register(WorkOrderChecklist)
class WorkOrderChecklistAdmin(admin.ModelAdmin):
    list_display = ("description", "work_order", "is_completed", "order")
    list_filter = ("is_completed",)
    search_fields = ("description",)
