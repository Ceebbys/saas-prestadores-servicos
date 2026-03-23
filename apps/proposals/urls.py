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
]
