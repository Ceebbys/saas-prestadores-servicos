from django.urls import path

from apps.contracts import views

app_name = "contracts"

urlpatterns = [
    path("", views.ContractListView.as_view(), name="list"),
    path("create/", views.ContractCreateView.as_view(), name="create"),
    path("<int:pk>/", views.ContractDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ContractUpdateView.as_view(), name="edit"),
    path(
        "from-proposal/<int:proposal_pk>/",
        views.ContractFromProposalView.as_view(),
        name="from_proposal",
    ),
    path(
        "<int:pk>/status/",
        views.ContractStatusView.as_view(),
        name="status",
    ),
    path(
        "<int:pk>/delete/",
        views.ContractDeleteView.as_view(),
        name="delete",
    ),
    # RV05 #11 — render compartilhado
    path(
        "<int:pk>/preview/",
        views.ContractPreviewView.as_view(),
        name="preview",
    ),
    path("<int:pk>/pdf/", views.ContractPDFView.as_view(), name="pdf"),
    path("<int:pk>/docx/", views.ContractDOCXView.as_view(), name="docx"),
]
