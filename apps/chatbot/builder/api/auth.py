"""Helpers de autenticação/autorização para o builder API (RV06).

`BuilderAPIView`: classe base que faz LoginRequired + valida tenant.
Toda view de builder herda dela ou usa o decorator `tenant_required`.
"""
from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View

from apps.chatbot.models import ChatbotFlow

MAX_GRAPH_BYTES = settings.CHATBOT_BUILDER_MAX_GRAPH_BYTES


class BuilderAPIView(LoginRequiredMixin, View):
    """Base para endpoints do builder visual.

    - Exige usuário autenticado (redireciona/401 se não).
    - Resolve `flow` via `pk` da URL e valida tenant em `dispatch`.
    - Helper `json_body(request)` lê + valida limite de tamanho.
    """

    raise_exception = True  # 403 ao invés de redirect (API)
    flow_pk_kwarg = "pk"

    flow: ChatbotFlow | None = None  # populated by _resolve_flow

    def dispatch(self, request: HttpRequest, *args, **kwargs):
        # Resolve flow + tenant (defesa contra IDOR)
        pk = kwargs.get(self.flow_pk_kwarg)
        if pk is not None:
            empresa = getattr(request, "empresa", None)
            if empresa is None:
                return JsonResponse({"error": "no_active_empresa"}, status=403)
            self.flow = get_object_or_404(
                ChatbotFlow,
                pk=pk,
                empresa=empresa,
            )
        return super().dispatch(request, *args, **kwargs)

    def json_body(self, request: HttpRequest) -> dict | JsonResponse:
        """Lê body JSON, validando limites de tamanho.

        Retorna `JsonResponse` (com status apropriado) em caso de erro;
        view deve retornar diretamente esse response. Use::

            body = self.json_body(request)
            if isinstance(body, JsonResponse):
                return body
            # body é dict
        """
        # Content-Length pré-check
        try:
            content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            content_length = 0
        if content_length and content_length > MAX_GRAPH_BYTES:
            return JsonResponse(
                {
                    "error": "payload_too_large",
                    "message": f"Payload excede o limite de {MAX_GRAPH_BYTES} bytes.",
                    "max_bytes": MAX_GRAPH_BYTES,
                },
                status=413,
            )
        try:
            raw = request.body
        except Exception:
            return JsonResponse({"error": "cannot_read_body"}, status=400)
        if len(raw) > MAX_GRAPH_BYTES:
            return JsonResponse(
                {
                    "error": "payload_too_large",
                    "message": f"Payload excede o limite de {MAX_GRAPH_BYTES} bytes.",
                    "max_bytes": MAX_GRAPH_BYTES,
                },
                status=413,
            )
        try:
            return json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            return JsonResponse(
                {"error": "invalid_json", "message": str(exc)},
                status=400,
            )
