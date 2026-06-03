"""STUBS Microsoft (Outlook Calendar / OneDrive). Não-funcionais neste round.

Integração real futura: Microsoft Graph API. Sem chamada de rede aqui.
"""
from __future__ import annotations

from .base import CalendarProvider, ProviderResult, StorageProvider


def _not_configured(capability: str) -> ProviderResult:
    return ProviderResult(
        status="not_configured", integration_ready=False,
        provider="microsoft", capability=capability,
    )


class MicrosoftCalendarProvider(CalendarProvider):
    def create_event(self, *, title, start, end, description="", attendees=None, **kwargs):
        # STUB: futuro → Microsoft Graph (/me/events).
        return _not_configured("calendar")

    def delete_event(self, event_id):
        return _not_configured("calendar")


class MicrosoftStorageProvider(StorageProvider):
    def create_folder(self, *, name, parent_id=None, **kwargs):
        # STUB: futuro → Microsoft Graph (/me/drive/root/children).
        return _not_configured("drive")

    def upload_file(self, *, folder_id, filename, content, **kwargs):
        return _not_configured("drive")

    def share_link(self, *, file_or_folder_id, **kwargs):
        return _not_configured("drive")
