from django.contrib import admin

from .models import Checklist, ChecklistItem


class ChecklistItemInline(admin.TabularInline):
    model = ChecklistItem
    extra = 0


@admin.register(Checklist)
class ChecklistAdmin(admin.ModelAdmin):
    list_display = ("name", "empresa", "content_type", "object_id", "order")
    list_filter = ("empresa", "content_type")
    search_fields = ("name",)
    inlines = [ChecklistItemInline]
