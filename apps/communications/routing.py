"""WebSocket routing do app communications.

Conectado em `config/asgi.py` via `ProtocolTypeRouter`.

Endpoints:
    /ws/inbox/          — live updates da lista de conversas + threads
    /ws/notifications/  — bell de notificações por usuário
"""
from django.urls import re_path

from apps.communications import consumers

websocket_urlpatterns = [
    re_path(r"^ws/inbox/$", consumers.InboxConsumer.as_asgi()),
    re_path(r"^ws/notifications/$", consumers.NotificationsConsumer.as_asgi()),
]
