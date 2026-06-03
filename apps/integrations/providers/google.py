"""STUBS Google (Calendar / Drive). Não-funcionais neste round.

Cada método retorna um ProviderResult "not_configured" e NÃO faz chamada de
rede. A integração real (google-api-python-client + OAuth) substitui o corpo
destes métodos numa rodada futura.
"""
from __future__ import annotations

from .base import CalendarProvider, ProviderResult, StorageProvider


def _not_configured(capability: str) -> ProviderResult:
    return ProviderResult(
        status="not_configured", integration_ready=False,
        provider="google", capability=capability,
    )


class GoogleCalendarProvider(CalendarProvider):
    def create_event(self, *, title, start, end, description="", attendees=None, **kwargs):
        # STUB: futuro → google-api-python-client (calendar v3) com
        # self.connection.get_access_token().
        return _not_configured("calendar")

    def delete_event(self, event_id):
        return _not_configured("calendar")


class GoogleStorageProvider(StorageProvider):
    def create_folder(self, *, name, parent_id=None, **kwargs):
        # STUB: futuro → Google Drive API (files.create, mimeType folder).
        return _not_configured("drive")

    def upload_file(self, *, folder_id, filename, content, **kwargs):
        return _not_configured("drive")

    def share_link(self, *, file_or_folder_id, **kwargs):
        return _not_configured("drive")
