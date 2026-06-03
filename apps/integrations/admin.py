from django.contrib import admin

from .models import AssistantConfig, IntegrationConnection


@admin.register(IntegrationConnection)
class IntegrationConnectionAdmin(admin.ModelAdmin):
    list_display = ("empresa", "provider", "status", "account_email", "last_synced_at")
    list_filter = ("provider", "status")
    exclude = ("access_token_encrypted", "refresh_token_encrypted")
    readonly_fields = ("last_synced_at", "last_error")


@admin.register(AssistantConfig)
class AssistantConfigAdmin(admin.ModelAdmin):
    list_display = ("empresa", "is_enabled", "llm_provider", "whatsapp_number")
    list_filter = ("is_enabled", "llm_provider")
    exclude = ("api_key_encrypted",)
