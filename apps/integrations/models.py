"""RV07 (Epic 7 + 6.1) — GROUNDWORK das integrações Google/Microsoft e do
Assistente IA. Tudo aqui é ADITIVO e não altera nenhum comportamento existente.

Os tokens OAuth são guardados criptografados reutilizando o mesmo helper Fernet
do projeto (apps.core.encryption) — NÃO inventamos cripto nova. Não há fluxo
OAuth real, refresh, nem chamadas de API neste round (ver services.py / providers).
"""
from __future__ import annotations

from django.db import models

from apps.core.encryption import decrypt, encrypt
from apps.core.models import TenantOwnedModel


class IntegrationConnection(TenantOwnedModel):
    """Conexão de um tenant a um provedor externo (Google/Microsoft).

    Uma linha por (empresa, provider). ``scopes`` rastreia quais capacidades
    (calendário/armazenamento) o consentimento cobre.
    """

    class Provider(models.TextChoices):
        GOOGLE = "google", "Google"
        MICROSOFT = "microsoft", "Microsoft"

    class Status(models.TextChoices):
        NOT_CONNECTED = "not_connected", "Não conectado"
        CONNECTED = "connected", "Conectado"
        EXPIRED = "expired", "Expirado"
        ERROR = "error", "Erro"

    class Capability(models.TextChoices):
        CALENDAR = "calendar", "Calendário"
        DRIVE = "drive", "Armazenamento"

    provider = models.CharField(max_length=20, choices=Provider.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.NOT_CONNECTED,
    )
    account_email = models.EmailField(blank=True)
    scopes = models.JSONField(default=list, blank=True)
    # --- material OAuth criptografado (Fernet via apps.core.encryption) ---
    access_token_encrypted = models.TextField(blank=True, editable=False)
    refresh_token_encrypted = models.TextField(blank=True, editable=False)
    token_type = models.CharField(max_length=40, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    # --- diagnóstico (espelha EmpresaEmailConfig.last_test_*) ---
    last_synced_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_error = models.TextField(blank=True, editable=False)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Conexão de Integração"
        verbose_name_plural = "Conexões de Integração"
        ordering = ["empresa", "provider"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "provider"],
                name="integration_connection_unique_provider_per_empresa",
            ),
        ]

    def __str__(self):
        return f"{self.get_provider_display()} — {self.get_status_display()}"

    # Acessores de token — reutilizam apps.core.encryption (NÃO cripto nova)
    def set_access_token(self, plaintext: str):
        self.access_token_encrypted = encrypt(plaintext or "")

    def get_access_token(self) -> str:
        return decrypt(self.access_token_encrypted) if self.access_token_encrypted else ""

    def set_refresh_token(self, plaintext: str):
        self.refresh_token_encrypted = encrypt(plaintext or "")

    def get_refresh_token(self) -> str:
        return decrypt(self.refresh_token_encrypted) if self.refresh_token_encrypted else ""

    @property
    def is_connected(self) -> bool:
        return self.status == self.Status.CONNECTED

    def has_capability(self, cap: str) -> bool:
        return cap in (self.scopes or [])


class AssistantConfig(TenantOwnedModel):
    """RV07 (Epic 6.1) — Config do assistente IA (LuzIA-like). SCAFFOLD.

    Apenas guarda configuração — não há loop agêntico nem chamadas a LLM neste
    round (ver assistant.py).
    """

    class Provider(models.TextChoices):
        NONE = "none", "Nenhum"
        OPENAI = "openai", "OpenAI"
        ANTHROPIC = "anthropic", "Anthropic"

    is_enabled = models.BooleanField("Ativo", default=False)
    whatsapp_number = models.CharField(
        max_length=32, blank=True,
        help_text="Número WhatsApp dedicado ao assistente (E.164).",
    )
    llm_provider = models.CharField(
        max_length=20, choices=Provider.choices, default=Provider.NONE,
    )
    model_name = models.CharField(max_length=80, blank=True)
    system_prompt = models.TextField(blank=True)
    api_key_encrypted = models.TextField(blank=True, editable=False)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Configuração do Assistente IA"
        verbose_name_plural = "Configurações do Assistente IA"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa"], name="assistant_config_unique_per_empresa",
            ),
        ]

    def __str__(self):
        return f"Assistente IA — {self.empresa_id} ({'on' if self.is_enabled else 'off'})"

    def set_api_key(self, plaintext: str):
        self.api_key_encrypted = encrypt(plaintext or "")

    def get_api_key(self) -> str:
        return decrypt(self.api_key_encrypted) if self.api_key_encrypted else ""
