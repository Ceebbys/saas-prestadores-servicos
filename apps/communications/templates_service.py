"""Serviço de renderização de MessageTemplate com Jinja2 sandboxed.

Variáveis suportadas:
    lead.{name, email, phone}
    contato.{name, email, phone, company}
    empresa.{name, slug}
    user.{first_name, email, full_name}
    now.{date, time, datetime}

Sandbox bloqueia atributos privados, attr lookup com __, e funções não
explicitamente permitidas. Renderiza com `autoescape=False` (texto puro,
não HTML). Caracteres invasivos no template não levantam — retorna
template literal se variável faltante.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.communications.models import Conversation, MessageTemplate

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Sandbox setup
# ----------------------------------------------------------------------------


_ENV_CACHE: dict = {}  # {"env": SandboxedEnvironment | None, "loaded": bool}


def _get_env():
    """Retorna SandboxedEnvironment cacheada (singleton)."""
    if _ENV_CACHE.get("loaded"):
        return _ENV_CACHE.get("env")

    try:
        from jinja2 import ChainableUndefined
        from jinja2.sandbox import SandboxedEnvironment
    except ImportError:
        logger.warning("Jinja2 não instalado — templates retornam content cru.")
        _ENV_CACHE["env"] = None
        _ENV_CACHE["loaded"] = True
        return None

    env = SandboxedEnvironment(
        autoescape=False,
        # Undefined complacente: variável faltante vira "" em vez de erro
        undefined=ChainableUndefined,
        trim_blocks=False,
        lstrip_blocks=False,
    )
    _ENV_CACHE["env"] = env
    _ENV_CACHE["loaded"] = True
    return env


# ----------------------------------------------------------------------------
# Context builders — extraem dados seguros e renomeados do request
# ----------------------------------------------------------------------------


class _SafeWrap:
    """Wrap leve sobre um objeto que só expõe atributos selecionados.

    Evita vazamento via {{ obj.password_encrypted }} ou similar.
    Implementa __getattr__ para devolver string vazia em atributos
    não explicitamente permitidos.
    """

    __slots__ = ("_obj", "_allowed")

    def __init__(self, obj, allowed: tuple):
        self._obj = obj
        self._allowed = allowed

    def __getattr__(self, name: str):
        if name.startswith("_"):
            return ""
        if self._allowed and name not in self._allowed:
            return ""
        val = getattr(self._obj, name, "")
        return val if val is not None else ""

    def __str__(self):
        # Em {{ lead }} → usa __str__
        return str(self._obj) if self._obj else ""


def _build_context(
    *,
    conversation=None,
    user=None,
    empresa=None,
) -> dict:
    """Constrói dict de variáveis para o template."""
    ctx = {}
    if conversation is not None:
        lead = getattr(conversation, "lead", None)
        contato = getattr(conversation, "contato", None) or (
            getattr(lead, "contato", None) if lead else None
        )
        ctx["lead"] = _SafeWrap(
            lead, ("name", "email", "phone", "company", "pk", "id"),
        )
        ctx["contato"] = _SafeWrap(
            contato, ("name", "email", "phone", "whatsapp", "company"),
        )
        if empresa is None:
            empresa = getattr(conversation, "empresa", None)
    ctx["empresa"] = _SafeWrap(empresa, ("name", "slug", "email", "phone"))
    if user is not None:
        ctx["user"] = _SafeWrap(
            user, ("email", "first_name_display", "full_name"),
        )
    else:
        ctx["user"] = _SafeWrap(None, ())

    now = datetime.now()
    ctx["now"] = {
        "date": now.strftime("%d/%m/%Y"),
        "time": now.strftime("%H:%M"),
        "datetime": now.strftime("%d/%m/%Y %H:%M"),
        "year": now.year,
    }
    return ctx


# ----------------------------------------------------------------------------
# API pública
# ----------------------------------------------------------------------------


def render_template(
    template,
    *,
    conversation=None,
    user=None,
    empresa=None,
) -> str:
    """Renderiza `template.content` no contexto da conversa/user/empresa.

    Args:
        template: MessageTemplate (ou objeto com .content string)
        conversation: Conversation (opcional)
        user: User (opcional)
        empresa: Empresa (opcional, default = conversation.empresa)

    Returns:
        String renderizada, ou content original se Jinja2 falhar.
    """
    if template is None:
        return ""
    content = getattr(template, "content", "") or ""
    if not content.strip():
        return content

    env = _get_env()
    if env is None:
        return content

    try:
        tpl = env.from_string(content)
        ctx = _build_context(
            conversation=conversation, user=user, empresa=empresa,
        )
        return tpl.render(**ctx)
    except Exception:  # noqa: BLE001
        logger.exception(
            "template_render_failed tpl_pk=%s",
            getattr(template, "pk", None),
        )
        return content


def render_and_track(template, **kwargs) -> str:
    """Render + incrementa usage_count (race-safe)."""
    rendered = render_template(template, **kwargs)
    try:
        from django.db.models import F
        from django.utils import timezone
        type(template).objects.filter(pk=template.pk).update(
            usage_count=F("usage_count") + 1,
            updated_at=timezone.now(),
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "template_usage_track_failed tpl_pk=%s",
            getattr(template, "pk", None),
        )
    return rendered
