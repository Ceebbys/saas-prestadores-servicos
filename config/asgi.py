"""ASGI entrypoint — HTTP + WebSocket via Django Channels.

HTTP segue pelo `get_asgi_application()` padrão do Django.
WebSocket é roteado para `apps.communications.routing` + outras apps via
`ProtocolTypeRouter`.

Em produção, o servidor é Daphne:

    daphne -b 0.0.0.0 -p 8000 config.asgi:application

`config/wsgi.py` continua existindo para compat com Gunicorn caso ainda
seja usado, mas o entrypoint oficial passa a ser este.
"""
from __future__ import annotations

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

# Importações de rotas APÓS django.setup() para garantir que models estejam carregados.
from apps.communications.routing import websocket_urlpatterns as comm_ws_urls  # noqa: E402

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(comm_ws_urls)
        )
    ),
})
