from django.contrib import admin

from .models import ChatbotAction, ChatbotChoice, ChatbotFlow, ChatbotStep


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
