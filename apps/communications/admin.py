from django.contrib import admin

from .models import (
    Conversation,
    ConversationMessage,
    MessageTemplate,
    Notification,
    PushSubscription,
)


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


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["pk", "user", "type", "title", "read_at", "created_at"]
    list_filter = ["type", "empresa"]
    search_fields = ["title", "body", "user__email"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ["pk", "user", "last_used_at", "created_at"]
    search_fields = ["user__email", "endpoint", "user_agent"]
    readonly_fields = ["endpoint", "p256dh", "auth", "user_agent", "created_at", "updated_at"]


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ["pk", "name", "shortcut", "category", "channel", "empresa", "is_active", "usage_count"]
    list_filter = ["category", "channel", "is_active", "empresa"]
    search_fields = ["name", "shortcut", "content"]
    readonly_fields = ["usage_count", "created_at", "updated_at"]
