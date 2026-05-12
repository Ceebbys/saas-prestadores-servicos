"""Recepção de e-mails via IMAP — polling per-tenant.

Faz par com `apps/communications/services.py::send_email` (saída SMTP).
A task Celery `apps.communications.tasks.poll_email_inboxes` chama
`poll_all_inboxes()` a cada 5 minutos pelo beat.

Fluxo por mensagem:
    UID SEARCH UNSEEN → FETCH RFC822 → parse → dedupe(message_id) →
    resolve lead → record_inbound() → STORE +FLAGS \\Seen

Idempotência em duas camadas:
- Server-side: só lê UNSEEN; só marca \\Seen DEPOIS de commit no DB.
- DB-side: dedupe por `payload.message_id` na `ConversationMessage`.

Robustez:
- Lock per-tenant via Django cache (Redis backend) com timeout 120s.
- Timeout TCP 15s no `IMAP4_SSL`.
- Try/except por-UID dentro do loop — falha de uma msg não derruba poll.
- Try/except envolvendo poll completo — falha de um tenant não impacta outros.
- `cfg.imap_last_poll_*` é gravado em sucesso E falha (UI sempre fresh).
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import imaplib
import logging
import socket
import time
from typing import TYPE_CHECKING, Any

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

if TYPE_CHECKING:
    from apps.accounts.models import Empresa, EmpresaEmailConfig
    from apps.contacts.models import Contato
    from apps.crm.models import Lead

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------------

#: Limite padrão de mensagens processadas por poll (evita runaway em caixas grandes).
DEFAULT_MAX_MESSAGES = 50

#: Timeout TCP em segundos (cobre LOGIN/SELECT/SEARCH/FETCH/STORE).
IMAP_TCP_TIMEOUT = 15

#: Limite de caracteres do corpo do e-mail antes de truncar.
BODY_MAX_CHARS = 50_000

#: TTL do lock per-tenant (em segundos).
LOCK_TIMEOUT = 120


# ----------------------------------------------------------------------------
# API pública
# ----------------------------------------------------------------------------


def poll_inbox_for_empresa(
    empresa,
    *,
    max_messages: int = DEFAULT_MAX_MESSAGES,
) -> dict:
    """Conecta no IMAP do tenant, lê UNSEEN, materializa em ConversationMessage.

    Retorna sumário:
        {
            "empresa_id": int,
            "fetched": int,       # UIDs visíveis após filtro UNSEEN+cap
            "ingested": int,      # mensagens novas criadas
            "skipped_dup": int,   # Message-ID já presente
            "errors": list[str],
            "duration_ms": int,
            "skipped_lock": bool, # True se outro worker já estava em flight
            "ok": bool,           # False se falha tenant-wide
        }

    Sempre atualiza `cfg.imap_last_poll_at/_ok/_error` (sucesso ou falha).
    """
    result = {
        "empresa_id": getattr(empresa, "pk", None),
        "fetched": 0,
        "ingested": 0,
        "skipped_dup": 0,
        "errors": [],
        "duration_ms": 0,
        "skipped_lock": False,
        "ok": False,
    }
    start_ts = time.monotonic()

    cfg = _get_email_config(empresa)
    if cfg is None:
        result["errors"].append("no_email_config")
        return result
    if not (cfg.imap_active and cfg.is_active and cfg.imap_host):
        result["errors"].append("imap_inactive")
        return result

    # ------------------------------------------------------------------
    # Lock per-tenant (Redis backend via Django cache)
    # ------------------------------------------------------------------
    lock_key = f"imap-poll-empresa-{empresa.pk}"
    got_lock = cache.add(lock_key, "1", timeout=LOCK_TIMEOUT)
    if not got_lock:
        logger.info(
            "imap_poll_skipped_lock empresa=%s — another worker is polling",
            empresa.pk,
        )
        result["skipped_lock"] = True
        result["duration_ms"] = int((time.monotonic() - start_ts) * 1000)
        return result

    try:
        conn = None
        try:
            conn = _open_connection(cfg)
            uids = _search_unseen_uids(conn, cfg.imap_folder, max_messages)
            result["fetched"] = len(uids)
            for uid in uids:
                try:
                    _process_uid(empresa, cfg, conn, uid, result)
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "imap_poll_msg_failed empresa=%s uid=%s",
                        empresa.pk, uid,
                    )
                    result["errors"].append(f"uid={uid}: {exc!r}"[:500])
                    # NÃO marca Seen — dedupe + UNSEEN re-tentam.
            if len(uids) >= max_messages:
                logger.warning(
                    "imap_backlog empresa=%s ingested=%s more_pending=true",
                    empresa.pk, result["ingested"],
                )
            # Sucesso tenant-wide (mesmo com erros por-msg isolados)
            result["ok"] = True
            _save_status(cfg, ok=True, error="")
        except Exception as exc:  # noqa: BLE001
            logger.exception("imap_poll_failed empresa=%s", empresa.pk)
            result["errors"].append(repr(exc)[:500])
            _save_status(cfg, ok=False, error=_sanitize_error(exc))
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:  # noqa: BLE001 — best-effort cleanup
                    pass
    finally:
        cache.delete(lock_key)

    result["duration_ms"] = int((time.monotonic() - start_ts) * 1000)
    return result


def poll_all_inboxes(
    *,
    max_messages_per_empresa: int = DEFAULT_MAX_MESSAGES,
) -> dict:
    """Itera todos os tenants com IMAP ativo. Falha de um não impacta outros.

    Retorna:
        {
            "polled": int,
            "tenants": list[dict],  # sumário per-tenant (poll_inbox_for_empresa)
            "errors": list[str],
        }
    """
    from apps.accounts.models import EmpresaEmailConfig

    summary = {"polled": 0, "tenants": [], "errors": []}
    configs = (
        EmpresaEmailConfig.objects
        .filter(imap_active=True, is_active=True)
        .exclude(imap_host="")
        .select_related("empresa")
    )
    for cfg in configs:
        empresa = cfg.empresa
        try:
            tenant_result = poll_inbox_for_empresa(
                empresa,
                max_messages=max_messages_per_empresa,
            )
            summary["tenants"].append(tenant_result)
            summary["polled"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("imap_poll_tenant_unhandled empresa=%s", empresa.pk)
            summary["errors"].append(f"empresa={empresa.pk}: {exc!r}"[:500])
    return summary


# ----------------------------------------------------------------------------
# Internos — conexão IMAP
# ----------------------------------------------------------------------------


def _open_connection(cfg) -> imaplib.IMAP4:
    """Abre conexão IMAP (SSL ou STARTTLS) e faz LOGIN.

    Levanta `imaplib.IMAP4.error` em falha de autenticação ou socket.timeout
    em falha de rede. Caller é responsável por chamar `conn.logout()`.
    """
    password = cfg.get_password()
    if cfg.imap_use_ssl:
        conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(
            host=cfg.imap_host,
            port=cfg.imap_port or 993,
            timeout=IMAP_TCP_TIMEOUT,
        )
    else:
        conn = imaplib.IMAP4(
            host=cfg.imap_host,
            port=cfg.imap_port or 143,
            timeout=IMAP_TCP_TIMEOUT,
        )
        try:
            conn.starttls()
        except imaplib.IMAP4.error:
            # Servidor pode não suportar STARTTLS — segue plaintext (raro mas válido)
            logger.warning(
                "imap_starttls_unavailable empresa_id=%s host=%s",
                cfg.empresa_id, cfg.imap_host,
            )
    conn.login(cfg.username, password)
    return conn


def _search_unseen_uids(conn, folder: str, limit: int) -> list[bytes]:
    """Faz SELECT na pasta + UID SEARCH UNSEEN, retorna primeiros `limit` UIDs."""
    safe_folder = folder or "INBOX"
    typ, _ = conn.select(safe_folder, readonly=False)
    if typ != "OK":
        raise imaplib.IMAP4.error(f"select_failed folder={safe_folder!r}")
    typ, data = conn.uid("SEARCH", None, "UNSEEN")
    if typ != "OK" or not data:
        return []
    raw_ids = data[0] or b""
    if not raw_ids:
        return []
    uids = raw_ids.split()
    return uids[:limit] if limit > 0 else []


def _fetch_raw(conn, uid: bytes) -> bytes:
    """UID FETCH RFC822, retorna bytes do corpo bruto."""
    typ, data = conn.uid("FETCH", uid, "(RFC822)")
    if typ != "OK" or not data or data[0] is None:
        raise imaplib.IMAP4.error(f"fetch_failed uid={uid!r}")
    # data[0] geralmente é uma tupla (header_str, raw_bytes); pegamos os bytes.
    item = data[0]
    if isinstance(item, tuple) and len(item) >= 2:
        return item[1]
    if isinstance(item, bytes):
        return item
    raise imaplib.IMAP4.error(f"fetch_unexpected_shape uid={uid!r}")


def _mark_seen(conn, uid: bytes) -> None:
    """STORE +FLAGS \\Seen — chamado SÓ após commit DB."""
    conn.uid("STORE", uid, "+FLAGS", "\\Seen")


# ----------------------------------------------------------------------------
# Internos — parsing
# ----------------------------------------------------------------------------


def _parse(raw: bytes) -> dict:
    """Parse RFC822 → dict normalizado.

    Retorna chaves: from_email, from_name, subject, body_text,
    message_id, in_reply_to, references, date (datetime ou None).
    """
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    from_raw = msg.get("From", "") or ""
    from_name, from_email = email.utils.parseaddr(str(from_raw))
    subject = str(msg.get("Subject", "") or "")
    message_id = str(msg.get("Message-ID", "") or "").strip()
    in_reply_to = str(msg.get("In-Reply-To", "") or "").strip()
    references = str(msg.get("References", "") or "").strip()
    date_obj = msg.get("Date")  # default policy retorna datetime quando possível
    if hasattr(date_obj, "isoformat"):
        date_value = date_obj
    else:
        # Compat: parseia string
        try:
            date_value = email.utils.parsedate_to_datetime(str(date_obj)) if date_obj else None
        except (TypeError, ValueError):
            date_value = None

    body_text = _extract_body(msg)

    return {
        "from_email": (from_email or "").strip().lower(),
        "from_name": (from_name or "").strip(),
        "subject": subject.strip(),
        "body_text": body_text,
        "message_id": message_id,
        "in_reply_to": in_reply_to,
        "references": references,
        "date": date_value,
    }


def _extract_body(msg) -> str:
    """Walk MIME: prefere text/plain; fallback text/html → nh3.clean(tags=set()).

    Limita a `BODY_MAX_CHARS`. Retorna sempre string (pode ser vazia).
    """
    text_plain = None
    text_html = None

    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            disposition = (part.get_content_disposition() or "").lower()
            if disposition == "attachment":
                continue
            ctype = (part.get_content_type() or "").lower()
            if ctype == "text/plain" and text_plain is None:
                text_plain = _safe_get_content(part)
            elif ctype == "text/html" and text_html is None:
                text_html = _safe_get_content(part)
            if text_plain:
                # Já temos plain — não precisamos continuar a procurar html
                break
    else:
        ctype = (msg.get_content_type() or "").lower()
        if ctype == "text/plain":
            text_plain = _safe_get_content(msg)
        elif ctype == "text/html":
            text_html = _safe_get_content(msg)

    if text_plain:
        body = text_plain.strip()
    elif text_html:
        body = _strip_html(text_html).strip()
    else:
        body = ""

    if len(body) > BODY_MAX_CHARS:
        body = body[:BODY_MAX_CHARS] + "\n\n[... mensagem truncada]"
    return body


def _safe_get_content(part) -> str:
    """Decodifica conteúdo de uma parte MIME, tolerando charsets quebrados."""
    try:
        return part.get_content()
    except (LookupError, UnicodeDecodeError):
        # Fallback manual com replace
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except LookupError:
            return payload.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def _strip_html(html: str) -> str:
    """Remove TODAS as tags HTML via nh3.clean(tags=set()), devolve texto puro."""
    try:
        import nh3
    except ImportError:
        # Fallback regex muito básico (não deve acontecer — nh3 está em requirements)
        import re
        return re.sub(r"<[^>]+>", "", html)
    cleaned = nh3.clean(html, tags=set(), attributes={})
    # nh3 não normaliza entidades como &nbsp; em todos os casos — normaliza com html
    import html as html_lib
    return html_lib.unescape(cleaned)


# ----------------------------------------------------------------------------
# Internos — resolução de lead/contato + ingestão
# ----------------------------------------------------------------------------


def _process_uid(empresa, cfg, conn, uid: bytes, result: dict) -> None:
    """Pipeline por-UID: fetch → parse → dedupe → resolve → record → mark seen."""
    raw = _fetch_raw(conn, uid)
    parsed = _parse(raw)

    if not parsed["from_email"]:
        logger.warning(
            "imap_msg_no_from empresa=%s uid=%s subject=%r",
            empresa.pk, uid, parsed["subject"][:50],
        )
        # Sem remetente: nada a fazer. Marca seen para não voltar.
        _mark_seen(conn, uid)
        return

    if parsed["message_id"] and _dedupe(empresa, parsed["message_id"]):
        _mark_seen(conn, uid)
        result["skipped_dup"] += 1
        return

    # Resolve lead/contato (cria se não existir)
    lead, contato, lead_created = _resolve_lead(
        empresa, parsed["from_email"], parsed["from_name"],
    )

    # Materializa via record_inbound (lazy import evita ciclo com Celery autoload)
    from apps.communications.services import record_inbound

    payload = {
        "message_id": parsed["message_id"],
        "in_reply_to": parsed["in_reply_to"],
        "references": parsed["references"],
        "subject": parsed["subject"],
        "date": parsed["date"].isoformat() if parsed["date"] else None,
        "source": "imap",
    }

    with transaction.atomic():
        conversation, _msg = record_inbound(
            empresa=empresa,
            lead=lead,
            channel="email",
            content=parsed["body_text"] or f"(sem corpo) — Assunto: {parsed['subject']}",
            sender_external_id=parsed["from_email"],
            sender_name=parsed["from_name"] or parsed["from_email"],
            payload=payload,
            contato=contato,
        )
        if lead_created:
            from apps.communications.services import add_internal_note
            add_internal_note(
                conversation,
                f"📥 Lead criado automaticamente via IMAP de {parsed['from_email']}.",
            )

    # SÓ marca \\Seen depois do commit
    _mark_seen(conn, uid)
    result["ingested"] += 1


def _dedupe(empresa, message_id: str) -> bool:
    """True se já existe ConversationMessage com este Message-ID neste tenant."""
    if not message_id:
        return False
    from apps.communications.models import ConversationMessage
    return ConversationMessage.objects.filter(
        conversation__empresa=empresa,
        channel="email",
        payload__message_id=message_id,
    ).exists()


def _resolve_lead(empresa, from_email: str, from_name: str) -> tuple[Any, Any, bool]:
    """Resolve (Lead, Contato, lead_created).

    Prioridade:
        1. Contato.email match → primeiro Lead do contato (ou cria Lead novo
           vinculado a esse Contato).
        2. Lead.email match (legado) → reusa Lead direto, sem contato.
        3. Sem match → cria Contato novo + Lead novo vinculado.
    """
    from apps.contacts.models import Contato
    from apps.crm.models import Lead

    # (1) Match por Contato
    contato = (
        Contato.objects
        .filter(empresa=empresa, email__iexact=from_email)
        .order_by("-updated_at")
        .first()
    )
    if contato is not None:
        lead = (
            Lead.objects
            .filter(empresa=empresa, contato=contato)
            .order_by("-updated_at")
            .first()
        )
        if lead is not None:
            return lead, contato, False
        # Contato existe sem Lead: cria Lead vinculado
        lead = Lead.objects.create(
            empresa=empresa,
            name=contato.name or from_name or from_email,
            contato=contato,
            email=from_email,  # legado preenchido para compat
            source=Lead.Source.OUTRO,
        )
        return lead, contato, True

    # (2) Match por Lead legado (sem Contato vinculado)
    legacy_lead = (
        Lead.objects
        .filter(empresa=empresa, email__iexact=from_email)
        .order_by("-updated_at")
        .first()
    )
    if legacy_lead is not None:
        return legacy_lead, getattr(legacy_lead, "contato", None), False

    # (3) Cria Contato + Lead novos
    new_contato = Contato.objects.create(
        empresa=empresa,
        name=from_name or from_email,
        email=from_email,
        source=Contato.Source.OUTRO,
    )
    new_lead = Lead.objects.create(
        empresa=empresa,
        name=from_name or from_email,
        contato=new_contato,
        email=from_email,
        source=Lead.Source.OUTRO,
    )
    return new_lead, new_contato, True


# ----------------------------------------------------------------------------
# Internos — status persistido
# ----------------------------------------------------------------------------


def _get_email_config(empresa):
    """Carrega EmpresaEmailConfig com tolerância a race-condition de delete."""
    from apps.accounts.models import EmpresaEmailConfig
    try:
        return EmpresaEmailConfig.objects.select_related("empresa").get(empresa=empresa)
    except EmpresaEmailConfig.DoesNotExist:
        return None


def _save_status(cfg, *, ok: bool, error: str) -> None:
    """Atualiza imap_last_poll_at/_ok/_error com tolerância a delete concorrente."""
    from apps.accounts.models import EmpresaEmailConfig
    try:
        EmpresaEmailConfig.objects.filter(pk=cfg.pk).update(
            imap_last_poll_at=timezone.now(),
            imap_last_poll_ok=ok,
            imap_last_poll_error=(error or "")[:1000],
            updated_at=timezone.now(),
        )
    except Exception:  # noqa: BLE001
        logger.exception("imap_status_save_failed cfg_pk=%s", cfg.pk)


def _sanitize_error(exc: BaseException) -> str:
    """Remove credenciais óbvias de mensagens de erro antes de gravar.

    `imaplib` raramente vaza senha mas alguns servidores fazem echo de comando
    no erro (ex.: "LOGIN user pass FAILED"). Filtra padrões conhecidos.
    """
    raw = repr(exc)
    # Truncate cedo para evitar gravar payloads gigantes
    raw = raw[:1000]
    # Limpeza heurística — não exaustiva, mas remove os casos mais comuns
    import re
    sanitized = re.sub(
        r"(LOGIN\s+\S+\s+)\S+",
        r"\1[REDACTED]",
        raw,
        flags=re.IGNORECASE,
    )
    return sanitized
