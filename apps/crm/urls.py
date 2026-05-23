from django.urls import path

from . import views

app_name = "crm"

urlpatterns = [
    # Leads
    path("leads/", views.LeadListView.as_view(), name="lead_list"),
    path("leads/create/", views.LeadCreateView.as_view(), name="lead_create"),
    path("leads/<int:pk>/", views.LeadDetailView.as_view(), name="lead_detail"),
    path("leads/<int:pk>/edit/", views.LeadUpdateView.as_view(), name="lead_update"),
    path("leads/<int:pk>/delete/", views.LeadDeleteView.as_view(), name="lead_delete"),
    path(
        "leads/<int:pk>/delete-cascade/",
        views.LeadDeleteCascadeView.as_view(),
        name="lead_delete_cascade",
    ),
    path("leads/<int:pk>/move/", views.LeadMoveView.as_view(), name="lead_move"),
    path(
        "leads/<int:lead_id>/contacts/new/",
        views.LeadContactCreateView.as_view(),
        name="lead_contact_create",
    ),
    path(
        "leads/contact-card/<int:contato_id>/",
        views.LeadContactCardView.as_view(),
        name="lead_contact_card",
    ),
    # Pipeline
    path("pipeline/", views.PipelineBoardView.as_view(), name="pipeline_board"),
    # RV06 — Configurar etapas (CRUD + flags ganho/perda)
    path(
        "pipeline/settings/",
        views.PipelineSettingsView.as_view(),
        name="pipeline_settings",
    ),
    path(
        "pipeline/stages/create/",
        views.PipelineStageCreateView.as_view(),
        name="pipeline_stage_create",
    ),
    path(
        "pipeline/stages/<int:pk>/edit/",
        views.PipelineStageUpdateView.as_view(),
        name="pipeline_stage_update",
    ),
    path(
        "pipeline/stages/<int:pk>/delete/",
        views.PipelineStageDeleteView.as_view(),
        name="pipeline_stage_delete",
    ),
    path(
        "pipeline/stages/<int:pk>/reorder/",
        views.PipelineStageReorderView.as_view(),
        name="pipeline_stage_reorder",
    ),
    # Opportunities
    path(
        "opportunities/create/",
        views.OpportunityCreateView.as_view(),
        name="opportunity_create",
    ),
    path(
        "opportunities/<int:pk>/",
        views.OpportunityDetailView.as_view(),
        name="opportunity_detail",
    ),
    path(
        "opportunities/<int:pk>/edit/",
        views.OpportunityUpdateView.as_view(),
        name="opportunity_update",
    ),
    path(
        "opportunities/<int:pk>/delete/",
        views.OpportunityDeleteView.as_view(),
        name="opportunity_delete",
    ),
    path(
        "opportunities/<int:pk>/move/",
        views.OpportunityMoveView.as_view(),
        name="opportunity_move",
    ),
]
