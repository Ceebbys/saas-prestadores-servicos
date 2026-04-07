from django.urls import path

from . import views

app_name = "chatbot"

urlpatterns = [
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
    # Actions (inline management)
    path("flows/<int:pk>/actions/add/", views.ActionAddView.as_view(), name="action_add"),
    path(
        "flows/<int:pk>/actions/<int:action_pk>/delete/",
        views.ActionDeleteView.as_view(),
        name="action_delete",
    ),
    # Webhook (stub)
    path("webhook/<uuid:token>/", views.webhook_receive, name="webhook_receive"),
]
