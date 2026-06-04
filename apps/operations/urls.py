from django.urls import path

from . import views

app_name = "operations"

urlpatterns = [
    # Work Orders
    path(
        "work-orders/",
        views.WorkOrderListView.as_view(),
        name="work_order_list",
    ),
    path(
        "work-orders/create/",
        views.WorkOrderCreateView.as_view(),
        name="work_order_create",
    ),
    path(
        "work-orders/<int:pk>/",
        views.WorkOrderDetailView.as_view(),
        name="work_order_detail",
    ),
    path(
        "work-orders/<int:pk>/edit/",
        views.WorkOrderUpdateView.as_view(),
        name="work_order_update",
    ),
    path(
        "work-orders/<int:pk>/delete/",
        views.WorkOrderDeleteView.as_view(),
        name="work_order_delete",
    ),
    path(
        "work-orders/<int:pk>/status/",
        views.WorkOrderStatusView.as_view(),
        name="work_order_status",
    ),
    path(
        "work-orders/<int:pk>/pdf/",
        views.WorkOrderPDFView.as_view(),
        name="work_order_pdf",
    ),
    # RV07 (Epic 7) — upload de arquivo da OS para o Google Drive
    path(
        "work-orders/<int:pk>/drive-upload/",
        views.WorkOrderDriveUploadView.as_view(),
        name="work_order_drive_upload",
    ),
    # Checklist toggle
    path(
        "work-orders/<int:wo_pk>/checklist/<int:item_pk>/toggle/",
        views.WorkOrderChecklistToggleView.as_view(),
        name="checklist_toggle",
    ),
    # Time tracker (RV07 3.1)
    path(
        "work-orders/<int:wo_pk>/timer/start/",
        views.WorkOrderTimerStartView.as_view(),
        name="timer_start",
    ),
    path(
        "work-orders/<int:wo_pk>/timer/<int:log_pk>/stop/",
        views.WorkOrderTimerStopView.as_view(),
        name="timer_stop",
    ),
    path(
        "work-orders/<int:wo_pk>/time-logs/create/",
        views.WorkOrderTimeLogCreateView.as_view(),
        name="time_log_create",
    ),
    path(
        "work-orders/<int:wo_pk>/time-logs/<int:log_pk>/edit/",
        views.WorkOrderTimeLogUpdateView.as_view(),
        name="time_log_update",
    ),
    path(
        "work-orders/<int:wo_pk>/time-logs/<int:log_pk>/delete/",
        views.WorkOrderTimeLogDeleteView.as_view(),
        name="time_log_delete",
    ),
    # Calendar
    path("calendar/", views.CalendarView.as_view(), name="calendar"),
    # Service Types (settings)
    path(
        "service-types/",
        views.ServiceTypeListView.as_view(),
        name="service_type_list",
    ),
]
