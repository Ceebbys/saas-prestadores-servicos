from django.urls import include, path

from . import views
from .whatsapp import evolution_webhook_auto, evolution_webhook_receive

app_name = "chatbot"

urlpatterns = [
    # RV06 — Builder visual (React Flow island) + API JSON
    path(
        "flows/<int:pk>/builder/",
        views.FlowBuilderView.as_view(),
        name="flow_builder",
    ),
    path("api/chatbot/", include("apps.chatbot.builder.api.urls")),

    # Flow CRUD
    path("flows/", views.FlowListView.as_view(), name="flow_list"),
    path("flows/create/", views.FlowCreateView.as_view(), name="flow_create"),
    path("flows/<int:pk>/", views.FlowDetailView.as_view(), name="flow_detail"),
    path("flows/<int:pk>/edit/", views.FlowUpdateView.as_view(), name="flow_update"),
    path("flows/<int:pk>/delete/", views.FlowDeleteView.as_view(), name="flow_delete"),
    path("flows/<int:pk>/toggle/", views.FlowToggleView.as_view(), name="flow_toggle"),
    # Steps (inline management)
    path("flows/<int:pk>/steps/add/", views.StepAddView.as_view(), name="step_add"),
    path(
        "flows/<int:pk>/steps/<int:step_pk>/edit/",
        views.StepUpdateView.as_view(),
        name="step_update",
    ),
    path(
        "flows/<int:pk>/steps/<int:step_pk>/delete/",
        views.StepDeleteView.as_view(),
        name="step_delete",
    ),
    path(
        "flows/<int:pk>/steps/<int:step_pk>/choices/",
        views.StepChoicesEditView.as_view(),
        name="step_choices_edit",
    ),
    # Actions (inline management)
    path("flows/<int:pk>/actions/add/", views.ActionAddView.as_view(), name="action_add"),
    path(
        "flows/<int:pk>/actions/<int:action_pk>/delete/",
        views.ActionDeleteView.as_view(),
        name="action_delete",
    ),
    # Public chat page (sem autenticação)
    path("chat/<uuid:token>/", views.public_chat, name="public_chat"),
    # API JSON (sem autenticação)
    path("api/<uuid:token>/start/", views.api_start_session, name="api_start"),
    path("api/<uuid:token>/respond/", views.api_respond, name="api_respond"),
    # Webhook (integração WhatsApp / genérica)
    path("webhook/<uuid:token>/", views.webhook_receive, name="webhook_receive"),
    # Evolution API WhatsApp adapter
    path("evolution/<uuid:token>/", evolution_webhook_receive, name="evolution_webhook"),
    path("evolution/", evolution_webhook_auto, name="evolution_webhook_auto"),
]
