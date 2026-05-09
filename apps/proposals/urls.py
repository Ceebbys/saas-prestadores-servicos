from django.urls import path

from apps.proposals import views

app_name = "proposals"

urlpatterns = [
    path("", views.ProposalListView.as_view(), name="list"),
    path("create/", views.ProposalCreateView.as_view(), name="create"),
    path("<int:pk>/", views.ProposalDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ProposalUpdateView.as_view(), name="edit"),
    path(
        "<int:proposal_pk>/items/add/",
        views.ProposalItemAddView.as_view(),
        name="item_add",
    ),
    path(
        "<int:proposal_pk>/items/<int:item_pk>/edit/",
        views.ProposalItemEditView.as_view(),
        name="item_edit",
    ),
    path(
        "<int:proposal_pk>/items/<int:item_pk>/delete/",
        views.ProposalItemDeleteView.as_view(),
        name="item_delete",
    ),
    path(
        "<int:pk>/status/",
        views.ProposalStatusView.as_view(),
        name="status",
    ),
    path(
        "<int:pk>/delete/",
        views.ProposalDeleteView.as_view(),
        name="delete",
    ),
    path("trash/", views.ProposalTrashView.as_view(), name="trash"),
    path(
        "<int:pk>/restore/",
        views.ProposalRestoreView.as_view(),
        name="restore",
    ),
    path(
        "<int:pk>/hard-delete/",
        views.ProposalHardDeleteView.as_view(),
        name="hard_delete",
    ),
    path(
        "<int:pk>/send/email/",
        views.ProposalSendEmailView.as_view(),
        name="send_email",
    ),
    path(
        "<int:pk>/send/whatsapp/",
        views.ProposalSendWhatsAppView.as_view(),
        name="send_whatsapp",
    ),
    path(
        "<int:pk>/preview/",
        views.ProposalPreviewView.as_view(),
        name="preview",
    ),
    path(
        "<int:pk>/pdf/",
        views.ProposalPDFView.as_view(),
        name="pdf",
    ),
    path(
        "<int:pk>/docx/",
        views.ProposalDOCXView.as_view(),
        name="docx",
    ),
    path(
        "<int:pk>/apply-template-items/",
        views.ProposalApplyTemplateItemsView.as_view(),
        name="apply_template_items",
    ),
    # Itens padrão de ProposalTemplate (HTMX — CRUD do template fica em settings_app)
    path(
        "templates/<int:template_pk>/items/add/",
        views.TemplateItemAddView.as_view(),
        name="template_item_add",
    ),
    path(
        "templates/<int:template_pk>/items/<int:item_pk>/delete/",
        views.TemplateItemDeleteView.as_view(),
        name="template_item_delete",
    ),
]
