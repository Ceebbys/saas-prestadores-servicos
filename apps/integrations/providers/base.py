"""Contratos abstratos dos provedores de integração (Calendário/Armazenamento).

Google e Microsoft compartilham este contrato. As implementações concretas
(google.py, microsoft.py) são STUBS não-funcionais neste round — retornam um
ProviderResult "not_configured" e NUNCA fazem chamada de rede, no mesmo espírito
dos stubs de Pix/Boleto em apps/finance/services.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderResult(dict):
    """Resultado padronizado (compatível com a convenção dos stubs do finance):
    {"status": "stub"|"not_configured"|"ok"|"error", "integration_ready": bool, ...}.
    """


class CalendarProvider(ABC):
    capability = "calendar"

    def __init__(self, connection):
        self.connection = connection

    @abstractmethod
    def create_event(self, *, title, start, end, description="", attendees=None, **kwargs) -> ProviderResult:
        ...

    @abstractmethod
    def delete_event(self, event_id: str) -> ProviderResult:
        ...

    # Não-abstratos: providers que não suportam herdam um no-op seguro
    # (assim o stub da Microsoft continua instanciável sem implementar).
    def list_events(self, *, time_min, time_max, **kwargs) -> ProviderResult:
        return ProviderResult(
            status="not_configured", integration_ready=False, capability="calendar",
        )

    def update_event(self, event_id, *, title, start, end,
                     description="", attendees=None, **kwargs) -> ProviderResult:
        return ProviderResult(
            status="not_configured", integration_ready=False, capability="calendar",
        )


class StorageProvider(ABC):
    capability = "drive"

    def __init__(self, connection):
        self.connection = connection

    @abstractmethod
    def create_folder(self, *, name, parent_id=None, **kwargs) -> ProviderResult:
        ...

    @abstractmethod
    def upload_file(self, *, folder_id, filename, content, **kwargs) -> ProviderResult:
        ...

    @abstractmethod
    def share_link(self, *, file_or_folder_id, **kwargs) -> ProviderResult:
        ...
