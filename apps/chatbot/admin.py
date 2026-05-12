from django.contrib import admin

from .models import (
    ChatbotAction,
    ChatbotChoice,
    ChatbotExecutionLog,
    ChatbotFlow,
    ChatbotFlowVersion,
    ChatbotMessage,
    ChatbotSecret,
    ChatbotStep,
)


class ChatbotStepInline(admin.TabularInline):
    model = ChatbotStep
    extra = 0


class ChatbotActionInline(admin.TabularInline):
    model = ChatbotAction
    extra = 0


@admin.register(ChatbotFlow)
class ChatbotFlowAdmin(admin.ModelAdmin):
    list_display = ["name", "channel", "is_active", "empresa"]
    list_filter = ["channel", "is_active"]
    inlines = [ChatbotStepInline, ChatbotActionInline]


@admin.register(ChatbotStep)
class ChatbotStepAdmin(admin.ModelAdmin):
    list_display = [
        "flow", "codigo_hierarquico", "order", "step_type",
        "lead_field_mapping", "is_required", "is_final",
    ]
    list_filter = ["step_type", "is_final"]
    readonly_fields = ["codigo_hierarquico", "nivel"]
    fields = [
        "flow", "order", "parent", "subordem",
        "question_text", "step_type", "lead_field_mapping",
        "is_required", "is_final",
        "codigo_hierarquico", "nivel",
    ]


@admin.register(ChatbotChoice)
class ChatbotChoiceAdmin(admin.ModelAdmin):
    list_display = ["step", "text", "order", "next_step"]


@admin.register(ChatbotAction)
class ChatbotActionAdmin(admin.ModelAdmin):
    list_display = ["flow", "trigger", "action_type"]
    list_filter = ["trigger", "action_type"]


# ---------------------------------------------------------------------------
# RV06 — Builder visual
# ---------------------------------------------------------------------------


@admin.register(ChatbotFlowVersion)
class ChatbotFlowVersionAdmin(admin.ModelAdmin):
    list_display = ["flow", "numero", "status", "published_at", "validated_at"]
    list_filter = ["status"]
    readonly_fields = ["numero", "validated_at", "validation_errors", "schema_version"]
    search_fields = ["flow__name", "notes"]


@admin.register(ChatbotMessage)
class ChatbotMessageAdmin(admin.ModelAdmin):
    list_display = ["session", "direction", "node_id", "created_at"]
    list_filter = ["direction"]
    search_fields = ["session__session_key", "content"]
    readonly_fields = ["session", "direction", "content", "payload", "node_id", "created_at"]


@admin.register(ChatbotExecutionLog)
class ChatbotExecutionLogAdmin(admin.ModelAdmin):
    list_display = ["session", "event", "level", "node_id", "created_at"]
    list_filter = ["event", "level"]
    search_fields = ["session__session_key", "node_id"]
    readonly_fields = ["session", "event", "level", "node_id", "payload", "created_at"]


@admin.register(ChatbotSecret)
class ChatbotSecretAdmin(admin.ModelAdmin):
    list_display = ["empresa", "name", "last_used_at", "created_at"]
    list_filter = ["empresa"]
    search_fields = ["name", "description"]
    # NÃO expor value_encrypted no admin form (Fernet binary)
    exclude = ["value_encrypted"]
    readonly_fields = ["empresa", "name", "description", "last_used_at", "created_by"]
