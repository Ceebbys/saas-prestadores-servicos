from django.contrib import admin

from .models import Conversation, ConversationMessage


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ["pk", "lead", "empresa", "status", "assigned_to", "last_message_at", "unread_count"]
    list_filter = ["status", "empresa"]
    search_fields = ["lead__name", "lead__email", "lead__phone", "last_message_preview"]
    readonly_fields = [
        "empresa", "lead", "last_message_at",
        "last_message_preview", "last_message_direction", "last_message_channel",
        "unread_count",
    ]


@admin.register(ConversationMessage)
class ConversationMessageAdmin(admin.ModelAdmin):
    list_display = ["pk", "conversation", "direction", "channel", "delivery_status", "created_at"]
    list_filter = ["direction", "channel", "delivery_status"]
    search_fields = ["content", "sender_external_id", "sender_name"]
    readonly_fields = [
        "conversation", "direction", "channel", "content", "payload",
        "sender_user", "sender_external_id", "sender_name",
        "delivery_status", "delivered_at", "read_at",
        "triggered_by_chatbot_session", "created_at",
    ]
