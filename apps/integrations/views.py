"""RV07 (Epic 7) — Views OAuth das integrações (Google).

Fluxo: Conectar → consentimento Google → callback (troca code por tokens) →
conexão CONNECTED. ``state`` (CSRF) fica na sessão, amarrado à empresa ativa.
Tudo escopado pela empresa via EmpresaMixin (login + request.empresa).
"""
from __future__ import annotations

import logging
import secrets

from django.contrib import messages
from django.shortcuts import redirect
from django.views import View

from apps.core.mixins import EmpresaMixin

from . import oauth
from .models import IntegrationConnection

logger = logging.getLogger(__name__)

_DEFAULT_CAPABILITIES = [
    IntegrationConnection.Capability.CALENDAR,
    IntegrationConnection.Capability.DRIVE,
]
_SETTINGS_REDIRECT = "settings_app:integrations"


class GoogleConnectView(EmpresaMixin, View):
    """Inicia o OAuth: gera state, guarda na sessão e manda pro Google."""

    def get(self, request):
        if not oauth.is_configured():
            messages.error(
                request,
                "Integração Google indisponível: as credenciais OAuth ainda não "
                "foram configuradas no servidor.",
            )
            return redirect(_SETTINGS_REDIRECT)

        state = secrets.token_urlsafe(32)
        request.session["google_oauth"] = {
            "state": state,
            "empresa_id": request.empresa.pk,
            "capabilities": list(_DEFAULT_CAPABILITIES),
        }
        return redirect(
            oauth.authorization_url(state=state, capabilities=_DEFAULT_CAPABILITIES)
        )


class GoogleCallbackView(EmpresaMixin, View):
    """Recebe o redirect do Google, valida state, troca code e conecta."""

    def get(self, request):
        sess = request.session.get("google_oauth") or {}

        if request.GET.get("error"):
            messages.error(
                request, f"Conexão com o Google cancelada ({request.GET['error']}).",
            )
            return self._done(request)

        state = request.GET.get("state", "")
        code = request.GET.get("code", "")
        if not state or state != sess.get("state"):
            messages.error(
                request, "Falha de segurança ao conectar (state inválido). Tente novamente.",
            )
            return self._done(request)
        if sess.get("empresa_id") != request.empresa.pk:
            messages.error(
                request, "A empresa ativa mudou durante a conexão. Tente novamente.",
            )
            return self._done(request)
        if not code:
            messages.error(request, "Código de autorização ausente na resposta do Google.")
            return self._done(request)

        capabilities = sess.get("capabilities") or list(_DEFAULT_CAPABILITIES)
        try:
            token = oauth.exchange_code(code)
            userinfo = oauth.fetch_userinfo(token.get("access_token", ""))
        except oauth.OAuthError as exc:
            logger.warning("integrations.google callback failed: %s", exc)
            messages.error(
                request, "Não foi possível concluir a conexão com o Google. Tente novamente.",
            )
            return self._done(request)

        conn, _ = IntegrationConnection.objects.get_or_create(
            empresa=request.empresa,
            provider=IntegrationConnection.Provider.GOOGLE,
        )
        oauth.apply_token_response(conn, token, capabilities=capabilities)
        conn.status = IntegrationConnection.Status.CONNECTED
        conn.account_email = userinfo.get("email", "") or conn.account_email
        conn.last_error = ""
        conn.save()

        suffix = f" ({conn.account_email})" if conn.account_email else ""
        messages.success(request, f"Google conectado{suffix}.")
        return self._done(request)

    def _done(self, request):
        request.session.pop("google_oauth", None)
        return redirect(_SETTINGS_REDIRECT)


class IntegrationDisconnectView(EmpresaMixin, View):
    """Desconecta o provedor: revoga (best-effort) e limpa tokens."""

    def post(self, request, provider):
        conn = IntegrationConnection.objects.filter(
            empresa=request.empresa, provider=provider,
        ).first()
        if conn is not None:
            if conn.provider == IntegrationConnection.Provider.GOOGLE:
                oauth.revoke(conn.get_access_token())
            conn.status = IntegrationConnection.Status.NOT_CONNECTED
            conn.access_token_encrypted = ""
            conn.refresh_token_encrypted = ""
            conn.scopes = []
            conn.expires_at = None
            conn.last_error = ""
            conn.save()
            messages.success(request, f"{conn.get_provider_display()} desconectado.")
        return redirect(_SETTINGS_REDIRECT)
