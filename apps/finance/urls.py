from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    # Overview
    path("", views.FinanceOverviewView.as_view(), name="finance_overview"),
    # Entries
    path("entries/", views.EntryListView.as_view(), name="entry_list"),
    path(
        "entries/create/",
        views.EntryCreateView.as_view(),
        name="entry_create",
    ),
    path(
        "entries/<int:pk>/edit/",
        views.EntryUpdateView.as_view(),
        name="entry_update",
    ),
    path(
        "entries/<int:pk>/pay/",
        views.EntryMarkPaidView.as_view(),
        name="entry_pay",
    ),
    # Categories (settings)
    path(
        "categories/",
        views.CategoryListView.as_view(),
        name="category_list",
    ),
]
