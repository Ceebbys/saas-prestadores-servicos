"""RV07 (Epic 7) — Rotas OAuth das integrações.

A rota de callback (``google/callback/``) é a que deve ser registrada como
"Authorized redirect URI" no Google Cloud Console.
"""
from django.urls import path

from . import views

app_name = "integrations"

urlpatterns = [
    path("google/connect/", views.GoogleConnectView.as_view(), name="google_connect"),
    path("google/callback/", views.GoogleCallbackView.as_view(), name="google_callback"),
    path(
        "<str:provider>/disconnect/",
        views.IntegrationDisconnectView.as_view(),
        name="disconnect",
    ),
]
