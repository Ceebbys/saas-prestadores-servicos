"""RV07 (Epic 7) — Provedores Google reais (Calendar v3 / Drive v3).

Usa httpx + o access_token (renovado on-demand por ``oauth.ensure_fresh``).
Cada chamada é defensiva: erro de rede/HTTP vira ``ProviderResult`` status
"error" (e grava ``last_error`` na conexão p/ diagnóstico) — nunca levanta, pra
não derrubar o fluxo de negócio que chamou (ex.: a task de follow-up).
"""
from __future__ import annotations

import datetime as _dt
import json
import logging

import httpx
from django.conf import settings
from django.utils import timezone

from .base import CalendarProvider, ProviderResult, StorageProvider

logger = logging.getLogger(__name__)

# Chamadas de dados rodam no caminho da requisição (carregar Calendário /
# salvar OS) — timeout curto p/ não travar a página se o Google estiver lento.
# A leitura é graciosa (cai p/ só as OS) e a escrita é best-effort.
_TIMEOUT = 10.0
_CALENDAR_EVENTS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
_DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
_DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"


def _ok(capability: str, **extra) -> ProviderResult:
    return ProviderResult(
        status="ok", integration_ready=True,
        provider="google", capability=capability, **extra,
    )


def _error(capability: str, detail: str) -> ProviderResult:
    return ProviderResult(
        status="error", integration_ready=False,
        provider="google", capability=capability, detail=detail[:300],
    )


def _format_when(value) -> dict:
    """Converte datetime/date/str p/ o objeto start|end do Calendar v3."""
    if isinstance(value, _dt.datetime):
        return {"dateTime": value.isoformat(), "timeZone": settings.TIME_ZONE}
    if isinstance(value, _dt.date):
        return {"date": value.isoformat()}
    return {"dateTime": str(value), "timeZone": settings.TIME_ZONE}


def _rfc3339(value) -> str:
    """timeMin/timeMax do events.list (RFC3339). Espera datetime aware."""
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day).isoformat() + "Z"
    return str(value)


class _GoogleMixin:
    """Plumbing comum: request autorizado com refresh + retry único no 401."""

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        from .. import oauth

        token = oauth.ensure_fresh(self.connection)
        headers = kwargs.pop("headers", {}) or {}
        headers["Authorization"] = f"Bearer {token}"
        resp = httpx.request(method, url, headers=headers, timeout=_TIMEOUT, **kwargs)
        if resp.status_code == 401:
            # token pode ter sido revogado/expirado fora da janela — força refresh
            try:
                token = oauth.refresh_access_token(self.connection)
            except oauth.OAuthError:
                return resp
            headers["Authorization"] = f"Bearer {token}"
            resp = httpx.request(method, url, headers=headers, timeout=_TIMEOUT, **kwargs)
        return resp

    def _record_ok(self):
        self.connection.last_synced_at = timezone.now()
        self.connection.last_error = ""
        self.connection.save(update_fields=["last_synced_at", "last_error", "updated_at"])

    def _record_error(self, detail: str):
        self.connection.last_error = (detail or "")[:500]
        self.connection.save(update_fields=["last_error", "updated_at"])


class GoogleCalendarProvider(_GoogleMixin, CalendarProvider):
    def create_event(self, *, title, start, end, description="", attendees=None, **kwargs):
        body = {
            "summary": title,
            "description": description or "",
            "start": _format_when(start),
            "end": _format_when(end),
        }
        if attendees:
            body["attendees"] = [{"email": e} for e in attendees if e]
        try:
            resp = self._request("POST", _CALENDAR_EVENTS, json=body)
        except httpx.HTTPError as exc:
            self._record_error(str(exc))
            return _error("calendar", f"rede: {exc}")
        if resp.status_code not in (200, 201):
            self._record_error(f"HTTP {resp.status_code}: {resp.text[:200]}")
            return _error("calendar", f"HTTP {resp.status_code}")
        data = resp.json()
        self._record_ok()
        return _ok(
            "calendar", event_id=data.get("id", ""),
            html_link=data.get("htmlLink", ""),
        )

    def delete_event(self, event_id):
        url = f"{_CALENDAR_EVENTS}/{event_id}"
        try:
            resp = self._request("DELETE", url)
        except httpx.HTTPError as exc:
            self._record_error(str(exc))
            return _error("calendar", f"rede: {exc}")
        # 204 = apagado; 410 = já não existe (idempotente)
        if resp.status_code in (200, 204, 404, 410):
            self._record_ok()
            return _ok("calendar", event_id=event_id)
        self._record_error(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return _error("calendar", f"HTTP {resp.status_code}")

    def list_events(self, *, time_min, time_max, max_results=250, **kwargs):
        params = {
            "timeMin": _rfc3339(time_min),
            "timeMax": _rfc3339(time_max),
            "singleEvents": "true",   # expande recorrentes em ocorrências
            "orderBy": "startTime",
            "maxResults": max_results,
        }
        try:
            resp = self._request("GET", _CALENDAR_EVENTS, params=params)
        except httpx.HTTPError as exc:
            self._record_error(str(exc))
            return _error("calendar", f"rede: {exc}")
        if resp.status_code != 200:
            self._record_error(f"HTTP {resp.status_code}: {resp.text[:200]}")
            return _error("calendar", f"HTTP {resp.status_code}")
        data = resp.json()
        items = []
        for ev in data.get("items", []):
            start = ev.get("start", {}) or {}
            end = ev.get("end", {}) or {}
            items.append({
                "id": ev.get("id", ""),
                "title": ev.get("summary") or "(sem título)",
                "start": start.get("dateTime") or start.get("date") or "",
                "end": end.get("dateTime") or end.get("date") or "",
                "all_day": "date" in start,
                "html_link": ev.get("htmlLink", ""),
            })
        self._record_ok()
        return _ok("calendar", items=items)

    def update_event(self, event_id, *, title, start, end,
                     description="", attendees=None, **kwargs):
        body = {
            "summary": title,
            "description": description or "",
            "start": _format_when(start),
            "end": _format_when(end),
        }
        if attendees:
            body["attendees"] = [{"email": e} for e in attendees if e]
        url = f"{_CALENDAR_EVENTS}/{event_id}"
        try:
            resp = self._request("PATCH", url, json=body)
        except httpx.HTTPError as exc:
            self._record_error(str(exc))
            return _error("calendar", f"rede: {exc}")
        if resp.status_code in (404, 410):
            # evento foi apagado no Google → sinaliza p/ o caller recriar
            return _error("calendar", "not_found")
        if resp.status_code not in (200, 201):
            self._record_error(f"HTTP {resp.status_code}: {resp.text[:200]}")
            return _error("calendar", f"HTTP {resp.status_code}")
        data = resp.json()
        self._record_ok()
        return _ok(
            "calendar", event_id=data.get("id", event_id),
            html_link=data.get("htmlLink", ""),
        )


class GoogleStorageProvider(_GoogleMixin, StorageProvider):
    def create_folder(self, *, name, parent_id=None, **kwargs):
        body = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            body["parents"] = [parent_id]
        try:
            resp = self._request(
                "POST", _DRIVE_FILES,
                params={"fields": "id,name,webViewLink"}, json=body,
            )
        except httpx.HTTPError as exc:
            self._record_error(str(exc))
            return _error("drive", f"rede: {exc}")
        if resp.status_code not in (200, 201):
            self._record_error(f"HTTP {resp.status_code}: {resp.text[:200]}")
            return _error("drive", f"HTTP {resp.status_code}")
        data = resp.json()
        self._record_ok()
        return _ok(
            "drive", file_id=data.get("id", ""), name=data.get("name", ""),
            web_link=data.get("webViewLink", ""),
        )

    def upload_file(self, *, folder_id, filename, content, mime="application/octet-stream", **kwargs):
        # Upload multipart/related (metadata JSON + bytes) num único POST.
        if isinstance(content, str):
            content = content.encode("utf-8")
        metadata = {"name": filename}
        if folder_id:
            metadata["parents"] = [folder_id]
        boundary = "servicopro-boundary-7e3f"
        body = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8") + content + f"\r\n--{boundary}--".encode("utf-8")
        headers = {"Content-Type": f"multipart/related; boundary={boundary}"}
        try:
            resp = self._request(
                "POST", _DRIVE_UPLOAD,
                params={"uploadType": "multipart", "fields": "id,name,webViewLink"},
                headers=headers, content=body,
            )
        except httpx.HTTPError as exc:
            self._record_error(str(exc))
            return _error("drive", f"rede: {exc}")
        if resp.status_code not in (200, 201):
            self._record_error(f"HTTP {resp.status_code}: {resp.text[:200]}")
            return _error("drive", f"HTTP {resp.status_code}")
        data = resp.json()
        self._record_ok()
        return _ok(
            "drive", file_id=data.get("id", ""), name=data.get("name", ""),
            web_link=data.get("webViewLink", ""),
        )

    def share_link(self, *, file_or_folder_id, **kwargs):
        # Concede leitura pública e devolve o link de visualização.
        perm_url = f"{_DRIVE_FILES}/{file_or_folder_id}/permissions"
        try:
            presp = self._request(
                "POST", perm_url, json={"role": "reader", "type": "anyone"},
            )
        except httpx.HTTPError as exc:
            self._record_error(str(exc))
            return _error("drive", f"rede: {exc}")
        if presp.status_code not in (200, 201):
            self._record_error(f"HTTP {presp.status_code}: {presp.text[:200]}")
            return _error("drive", f"HTTP {presp.status_code}")
        # Busca o webViewLink (link amigável)
        link = ""
        try:
            gresp = self._request(
                "GET", f"{_DRIVE_FILES}/{file_or_folder_id}",
                params={"fields": "webViewLink"},
            )
            if gresp.status_code == 200:
                link = gresp.json().get("webViewLink", "")
        except httpx.HTTPError:
            pass
        if not link:
            link = f"https://drive.google.com/file/d/{file_or_folder_id}/view"
        self._record_ok()
        return _ok("drive", web_link=link, file_id=file_or_folder_id)
