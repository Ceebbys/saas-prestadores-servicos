from django.urls import path

from . import views

app_name = "checklists"

urlpatterns = [
    path(
        "<str:owner_type>/<int:owner_id>/add/",
        views.ChecklistAddView.as_view(),
        name="add",
    ),
    path("<int:pk>/rename/", views.ChecklistRenameView.as_view(), name="rename"),
    path("<int:pk>/delete/", views.ChecklistDeleteView.as_view(), name="delete"),
    path("<int:pk>/items/add/", views.ChecklistItemAddView.as_view(), name="item_add"),
    path(
        "items/<int:item_pk>/toggle/",
        views.ChecklistItemToggleView.as_view(),
        name="item_toggle",
    ),
    path(
        "items/<int:item_pk>/edit/",
        views.ChecklistItemEditView.as_view(),
        name="item_edit",
    ),
    path(
        "items/<int:item_pk>/delete/",
        views.ChecklistItemDeleteView.as_view(),
        name="item_delete",
    ),
]
