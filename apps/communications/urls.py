from django.urls import path

from . import views
from . import views_notifications
from . import views_templates

app_name = "communications"

urlpatterns = [
    path("", views.InboxView.as_view(), name="inbox"),
    path("<int:pk>/", views.ConversationDetailView.as_view(), name="detail"),
    path("<int:pk>/send/", views.SendMessageView.as_view(), name="send"),
    path("<int:pk>/status/", views.ChangeStatusView.as_view(), name="status"),
    path("<int:pk>/assign/", views.AssignView.as_view(), name="assign"),
    path("<int:pk>/quick-action/", views.QuickActionView.as_view(), name="quick_action"),
    path("<int:pk>/mark-read/", views.MarkReadView.as_view(), name="mark_read"),
    # Notificações (Fase 4)
    path(
        "notifications/", views_notifications.NotificationListView.as_view(),
        name="notification_list",
    ),
    path(
        "notifications/dropdown/",
        views_notifications.NotificationDropdownView.as_view(),
        name="notification_dropdown",
    ),
    path(
        "notifications/<int:pk>/read/",
        views_notifications.NotificationMarkReadView.as_view(),
        name="notification_mark_read",
    ),
    path(
        "notifications/mark-all-read/",
        views_notifications.NotificationMarkAllReadView.as_view(),
        name="notification_mark_all_read",
    ),
    path(
        "notifications/push-subscribe/",
        views_notifications.PushSubscribeView.as_view(),
        name="push_subscribe",
    ),
    path(
        "notifications/push-unsubscribe/",
        views_notifications.PushUnsubscribeView.as_view(),
        name="push_unsubscribe",
    ),
    path(
        "notifications/vapid-public-key/",
        views_notifications.VapidPublicKeyView.as_view(),
        name="vapid_public_key",
    ),
    # Templates de mensagem (Fase 5 — resposta rápida)
    path(
        "templates/",
        views_templates.TemplateListView.as_view(),
        name="template_list",
    ),
    path(
        "templates/create/",
        views_templates.TemplateCreateView.as_view(),
        name="template_create",
    ),
    path(
        "templates/<int:pk>/edit/",
        views_templates.TemplateUpdateView.as_view(),
        name="template_update",
    ),
    path(
        "templates/<int:pk>/delete/",
        views_templates.TemplateDeleteView.as_view(),
        name="template_delete",
    ),
    # Endpoint usado pelo composer para listar + buscar
    path(
        "templates/api/search/",
        views_templates.TemplateSearchView.as_view(),
        name="template_search",
    ),
    # Render do template no contexto da conversa (preview / inserção)
    path(
        "templates/api/<int:pk>/render/<int:conv_pk>/",
        views_templates.TemplateRenderView.as_view(),
        name="template_render",
    ),
]
