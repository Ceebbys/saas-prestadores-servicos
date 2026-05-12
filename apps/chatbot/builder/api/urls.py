"""URLs do builder API (RV06).

Prefixo `/api/chatbot/` montado em `apps/chatbot/urls.py`.
"""
from django.urls import path

from . import views

urlpatterns = [
    # Catálogo de tipos de bloco (global)
    path(
        "node-catalog/",
        views.node_catalog_view,
        name="node_catalog",
    ),
    # Operações sobre um flow específico
    path(
        "flows/<int:pk>/graph/",
        views.GraphView.as_view(),
        name="builder_graph",
    ),
    path(
        "flows/<int:pk>/graph/save/",
        views.GraphSaveView.as_view(),
        name="builder_save",
    ),
    path(
        "flows/<int:pk>/validate/",
        views.GraphValidateView.as_view(),
        name="builder_validate",
    ),
    path(
        "flows/<int:pk>/publish/",
        views.GraphPublishView.as_view(),
        name="builder_publish",
    ),
    path(
        "flows/<int:pk>/builder/init/",
        views.BuilderInitView.as_view(),
        name="builder_init",
    ),
]
