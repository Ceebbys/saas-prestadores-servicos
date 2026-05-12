from django.urls import path

from . import views

app_name = "communications"

urlpatterns = [
    path("", views.InboxView.as_view(), name="inbox"),
    path("<int:pk>/", views.ConversationDetailView.as_view(), name="detail"),
    path("<int:pk>/send/", views.SendMessageView.as_view(), name="send"),
    path("<int:pk>/status/", views.ChangeStatusView.as_view(), name="status"),
    path("<int:pk>/assign/", views.AssignView.as_view(), name="assign"),
    path("<int:pk>/quick-action/", views.QuickActionView.as_view(), name="quick_action"),
    path("<int:pk>/mark-read/", views.MarkReadView.as_view(), name="mark_read"),
]
