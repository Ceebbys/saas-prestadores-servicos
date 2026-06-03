from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    # Overview
    path("", views.FinanceOverviewView.as_view(), name="finance_overview"),
    # RV10 — Backfill on-demand de entries de leads ganhos sem lançamento
    path(
        "backfill-won-leads/",
        views.BackfillWonLeadEntriesView.as_view(),
        name="backfill_won_leads",
    ),
    # RV07 — Re-sincroniza valor de lançamentos auto-gerados zerados
    path(
        "resync-zero-values/",
        views.ResyncZeroValuesView.as_view(),
        name="resync_zero_values",
    ),
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
    # RV10 — Excluir lançamento (hard delete)
    path(
        "entries/<int:pk>/delete/",
        views.EntryDeleteView.as_view(),
        name="entry_delete",
    ),
    # Categories (settings)
    path(
        "categories/",
        views.CategoryListView.as_view(),
        name="category_list",
    ),
]
