"""RV07 (Epic 7) — OAuth 2.0 do Google (Authorization Code + refresh).

UM app OAuth do SaaS (credenciais em settings); cada tenant conecta a SUA conta
Google ao app. Usa httpx (já é dependência) — sem SDK pesado do Google. Os
tokens ficam criptografados no IntegrationConnection (Fernet), nunca em claro.

Sem GOOGLE_OAUTH_CLIENT_ID/SECRET configurados, ``is_configured()`` é False e o
botão "Conectar" fica desabilitado — a integração inteira é um no-op seguro.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.utils import timezone

from .models import IntegrationConnection

logger = logging.getLogger(__name__)

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

# Escopo mínimo por capacidade (princípio do menor privilégio).
#   calendar.events → criar/apagar eventos (não lê toda a agenda)
#   drive.file      → só os arquivos que o app cria (não a Drive inteira)
_SCOPE_BY_CAPABILITY = {
    IntegrationConnection.Capability.CALENDAR: "https://www.googleapis.com/auth/calendar.events",
    IntegrationConnection.Capability.DRIVE: "https://www.googleapis.com/auth/drive.file",
}
_BASE_SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]

_HTTP_TIMEOUT = 20.0
# margem para renovar o token ANTES de expirar de fato
_REFRESH_SKEW = timedelta(seconds=60)


class OAuthError(Exception):
    """Falha no fluxo OAuth (troca/refresh/userinfo)."""


def is_configured() -> bool:
    return bool(
        getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")
        and getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    )


def redirect_uri() -> str:
    return getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", "")


def scopes_for(capabilities) -> list[str]:
    """Lista de scopes p/ as capacidades pedidas (sempre inclui os base)."""
    scopes = list(_BASE_SCOPES)
    for cap in capabilities or []:
        scope = _SCOPE_BY_CAPABILITY.get(cap)
        if scope and scope not in scopes:
            scopes.append(scope)
    return scopes


def authorization_url(*, state: str, capabilities) -> str:
    """URL de consentimento do Google para o tenant autorizar."""
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(scopes_for(capabilities)),
        "access_type": "offline",        # queremos refresh_token
        "prompt": "consent",             # garante refresh_token mesmo em re-consent
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Troca o ``code`` do callback por tokens. Levanta OAuthError em falha."""
    data = {
        "code": code,
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": redirect_uri(),
        "grant_type": "authorization_code",
    }
    try:
        resp = httpx.post(TOKEN_ENDPOINT, data=data, timeout=_HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        raise OAuthError(f"token exchange falhou: {exc}") from exc
    if resp.status_code != 200:
        raise OAuthError(f"token exchange HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def fetch_userinfo(access_token: str) -> dict:
    """Dados básicos da conta (usamos o e-mail p/ rotular a conexão)."""
    try:
        resp = httpx.get(
            USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise OAuthError(f"userinfo falhou: {exc}") from exc
    if resp.status_code != 200:
        raise OAuthError(f"userinfo HTTP {resp.status_code}")
    return resp.json()


def apply_token_response(connection, token: dict, *, capabilities=None) -> None:
    """Copia tokens/expiração do payload para o ``connection`` (NÃO salva).

    Google só devolve ``refresh_token`` no 1º consentimento (ou com
    prompt=consent) — preservamos o existente quando não vier outro.
    """
    access = token.get("access_token") or ""
    if access:
        connection.set_access_token(access)
    refresh = token.get("refresh_token")
    if refresh:
        connection.set_refresh_token(refresh)
    connection.token_type = token.get("token_type", "") or connection.token_type
    expires_in = token.get("expires_in")
    if expires_in:
        connection.expires_at = timezone.now() + timedelta(seconds=int(expires_in))
    if capabilities is not None:
        connection.scopes = list(capabilities)


def refresh_access_token(connection) -> str:
    """Renova o access_token via refresh_token e salva. Retorna o novo token."""
    refresh = connection.get_refresh_token()
    if not refresh:
        raise OAuthError("sem refresh_token; reconecte a conta")
    data = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    }
    try:
        resp = httpx.post(TOKEN_ENDPOINT, data=data, timeout=_HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        raise OAuthError(f"refresh falhou: {exc}") from exc
    if resp.status_code != 200:
        raise OAuthError(f"refresh HTTP {resp.status_code}: {resp.text[:200]}")
    apply_token_response(connection, resp.json())  # mantém scopes/refresh atuais
    connection.save(update_fields=[
        "access_token_encrypted", "refresh_token_encrypted",
        "token_type", "expires_at", "updated_at",
    ])
    return connection.get_access_token()


def ensure_fresh(connection) -> str:
    """Access token válido, renovando se faltar pouco p/ expirar.

    Se não der pra renovar (sem refresh_token), devolve o atual — quem chama a
    API trata o 401 e marca a conexão como expirada.
    """
    if connection.expires_at and connection.expires_at > timezone.now() + _REFRESH_SKEW:
        return connection.get_access_token()
    try:
        return refresh_access_token(connection)
    except OAuthError:
        logger.warning("integrations.google: refresh indisponível conn=%s", connection.pk)
        return connection.get_access_token()


def revoke(token: str) -> None:
    """Best-effort: revoga o token no Google. Nunca levanta."""
    if not token:
        return
    try:
        httpx.post(REVOKE_ENDPOINT, params={"token": token}, timeout=_HTTP_TIMEOUT)
    except httpx.HTTPError:
        logger.debug("integrations.google: revoke falhou (ignorado)")
