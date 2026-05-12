"""Testes do poller IMAP per-tenant.

Mockam `_open_connection` para retornar uma `FakeImapConn` em memória —
nenhum socket real é aberto. Cobertura crítica:

- Smoke import (pega o bug de pacote quebrado)
- Extração text/plain preferido
- Fallback text/html via nh3.clean(tags=set())
- Dedupe por Message-ID em payload
- Resolução de lead: Contato → Lead legado → criar novo + nota
- Isolamento de falhas entre tenants
- Lock per-tenant skip
- Cap max_messages
- \\Seen só após commit
- View de teste de conexão
"""
from __future__ import annotations

import email.message
import email.policy
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import EmpresaEmailConfig
from apps.communications.models import (
    Conversation,
    ConversationMessage,
    get_or_create_conversation,
)
from apps.contacts.models import Contato
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead


# ----------------------------------------------------------------------------
# Helpers para construir mensagens RFC822 e fake IMAP connection
# ----------------------------------------------------------------------------


def build_raw_message(
    *,
    from_addr: str = "cliente@exemplo.com",
    from_name: str = "Cliente Teste",
    subject: str = "Assunto teste",
    text_body: str | None = "Corpo em texto puro\nlinha 2",
    html_body: str | None = None,
    message_id: str = "<msg-001@example.com>",
    in_reply_to: str = "",
    date: str = "Tue, 12 May 2026 10:00:00 -0300",
) -> bytes:
    """Constrói bytes RFC822 com policy SMTP."""
    msg = email.message.EmailMessage(policy=email.policy.SMTP)
    msg["From"] = f"{from_name} <{from_addr}>" if from_name else from_addr
    msg["To"] = "destino@empresa.com"
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    msg["Date"] = date

    if text_body is not None and html_body is not None:
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")
    elif html_body is not None:
        msg.set_content(html_body, subtype="html")
    elif text_body is not None:
        msg.set_content(text_body)
    else:
        msg.set_content("")
    return bytes(msg)


class FakeImapConn:
    """Conexão IMAP fake. Responde a select/uid('SEARCH','FETCH','STORE')/logout."""

    def __init__(self, messages: list[tuple[bytes, bytes]] | None = None):
        self.messages = messages or []
        self.seen_uids: list[bytes] = []
        self.selected_folder: str | None = None
        self.logged_out = False

    def select(self, folder, readonly=False):
        self.selected_folder = folder
        return ("OK", [b"OK"])

    def uid(self, command, *args):
        cmd = command.upper()
        if cmd == "SEARCH":
            uids = b" ".join(uid for uid, _ in self.messages)
            return ("OK", [uids])
        if cmd == "FETCH":
            uid = args[0]
            for u, raw in self.messages:
                if u == uid:
                    return ("OK", [(b"header", raw)])
            return ("NO", [None])
        if cmd == "STORE":
            uid = args[0]
            self.seen_uids.append(uid)
            return ("OK", [b""])
        return ("BAD", [b"unknown"])

    def login(self, *args, **kwargs):
        return ("OK", [b""])

    def logout(self):
        self.logged_out = True
        return ("BYE", [b""])

    def starttls(self):
        return ("OK", [b""])


# ----------------------------------------------------------------------------
# Base com setup compartilhado
# ----------------------------------------------------------------------------


class ImapBaseTest(TestCase):
    def setUp(self):
        # Limpa cache de locks entre testes
        cache.clear()
        self.empresa = create_test_empresa()
        self.user = create_test_user("admin@t.com", "Admin", self.empresa)
        self.cfg = EmpresaEmailConfig.objects.create(
            empresa=self.empresa,
            host="smtp.example.com", port=587, username="user@example.com",
            from_email="user@example.com", from_name="Test",
            is_active=True,
            imap_host="imap.example.com", imap_port=993, imap_use_ssl=True,
            imap_folder="INBOX", imap_active=True,
        )
        self.cfg.set_password("dummypass")
        self.cfg.save()


# ----------------------------------------------------------------------------
# 1. Smoke: imports estão saudáveis
# ----------------------------------------------------------------------------


class ImportSmokeTests(TestCase):
    """Pega exatamente o bug de pacote services/ quebrado."""

    def test_services_imports(self):
        from apps.communications.services import (  # noqa: F401
            add_internal_note,
            record_bot_outbound,
            record_inbound,
            send_email,
            send_whatsapp,
        )

    def test_services_imap_imports(self):
        from apps.communications.services_imap import (  # noqa: F401
            poll_all_inboxes,
            poll_inbox_for_empresa,
        )

    def test_tasks_imports(self):
        from apps.communications.tasks import poll_email_inboxes  # noqa: F401
        self.assertEqual(
            poll_email_inboxes.name,
            "apps.communications.tasks.poll_email_inboxes",
        )


# ----------------------------------------------------------------------------
# 2. Body extraction & parsing
# ----------------------------------------------------------------------------


class BodyExtractionTests(TestCase):
    def test_text_plain_preferred_over_html(self):
        from apps.communications.services_imap import _parse
        raw = build_raw_message(
            text_body="texto puro aqui",
            html_body="<p><strong>html</strong> aqui</p>",
            message_id="<a@x>",
        )
        parsed = _parse(raw)
        self.assertIn("texto puro", parsed["body_text"])
        self.assertNotIn("<p>", parsed["body_text"])

    def test_html_fallback_strips_tags(self):
        from apps.communications.services_imap import _parse
        raw = build_raw_message(
            text_body=None,
            html_body="<p>Olá <b>mundo</b>!</p><script>alert('x')</script>",
            message_id="<html@x>",
        )
        parsed = _parse(raw)
        self.assertIn("Olá", parsed["body_text"])
        self.assertIn("mundo", parsed["body_text"])
        self.assertNotIn("<p>", parsed["body_text"])
        self.assertNotIn("<script>", parsed["body_text"])
        self.assertNotIn("alert", parsed["body_text"])

    def test_parse_extracts_headers(self):
        from apps.communications.services_imap import _parse
        raw = build_raw_message(
            from_addr="alguem@dominio.com.br",
            from_name="Fulano de Tal",
            subject="Orçamento de obra",
            message_id="<hdr-1@x>",
            in_reply_to="<original@y>",
        )
        parsed = _parse(raw)
        self.assertEqual(parsed["from_email"], "alguem@dominio.com.br")
        self.assertEqual(parsed["from_name"], "Fulano de Tal")
        self.assertEqual(parsed["subject"], "Orçamento de obra")
        self.assertEqual(parsed["message_id"], "<hdr-1@x>")
        self.assertEqual(parsed["in_reply_to"], "<original@y>")

    def test_parse_lowercases_email(self):
        from apps.communications.services_imap import _parse
        raw = build_raw_message(from_addr="Mixed@Case.COM", message_id="<c@x>")
        parsed = _parse(raw)
        self.assertEqual(parsed["from_email"], "mixed@case.com")


# ----------------------------------------------------------------------------
# 3. Dedupe por Message-ID
# ----------------------------------------------------------------------------


class DedupeTests(ImapBaseTest):
    def test_dedupe_skips_existing_message_id(self):
        from apps.communications import services_imap

        # Pré-cria mensagem com Message-ID que vai chegar pelo IMAP
        lead = Lead.objects.create(
            empresa=self.empresa, name="Pre", email="dup@test.com",
        )
        conv = get_or_create_conversation(self.empresa, lead)
        ConversationMessage.objects.create(
            conversation=conv,
            direction=ConversationMessage.Direction.INBOUND,
            channel=ConversationMessage.Channel.EMAIL,
            content="já existe",
            payload={"message_id": "<dup-001@example.com>"},
        )
        initial_count = ConversationMessage.objects.count()

        fake = FakeImapConn(messages=[
            (b"1", build_raw_message(
                from_addr="dup@test.com",
                message_id="<dup-001@example.com>",
            )),
        ])
        with patch.object(services_imap, "_open_connection", return_value=fake):
            result = services_imap.poll_inbox_for_empresa(self.empresa)

        self.assertEqual(result["skipped_dup"], 1)
        self.assertEqual(result["ingested"], 0)
        # Marcou Seen para não voltar
        self.assertEqual(fake.seen_uids, [b"1"])
        # Nenhuma nova ConversationMessage criada
        self.assertEqual(ConversationMessage.objects.count(), initial_count)


# ----------------------------------------------------------------------------
# 4. Resolução de Lead/Contato
# ----------------------------------------------------------------------------


class LeadResolutionTests(ImapBaseTest):
    def test_resolves_existing_contato_with_lead(self):
        from apps.communications import services_imap

        contato = Contato.objects.create(
            empresa=self.empresa,
            name="Antigo",
            email="velho@cliente.com",
        )
        existing_lead = Lead.objects.create(
            empresa=self.empresa, name="Lead Antigo", contato=contato,
        )

        fake = FakeImapConn(messages=[
            (b"1", build_raw_message(
                from_addr="velho@cliente.com",
                message_id="<reuse-c@x>",
            )),
        ])
        with patch.object(services_imap, "_open_connection", return_value=fake):
            result = services_imap.poll_inbox_for_empresa(self.empresa)

        self.assertEqual(result["ingested"], 1)
        # Conversation deve estar atrelada ao lead existente
        conv = Conversation.objects.get(lead=existing_lead)
        self.assertEqual(conv.empresa, self.empresa)
        # Sem nota interna automática (não foi criado novo)
        notes = conv.messages.filter(
            channel=ConversationMessage.Channel.INTERNAL_NOTE,
        ).count()
        self.assertEqual(notes, 0)

    def test_resolves_legacy_lead_by_email(self):
        from apps.communications import services_imap

        legacy_lead = Lead.objects.create(
            empresa=self.empresa, name="Lead Legado", email="legado@x.com",
        )

        fake = FakeImapConn(messages=[
            (b"1", build_raw_message(
                from_addr="legado@x.com",
                message_id="<legacy@x>",
            )),
        ])
        with patch.object(services_imap, "_open_connection", return_value=fake):
            result = services_imap.poll_inbox_for_empresa(self.empresa)

        self.assertEqual(result["ingested"], 1)
        self.assertTrue(
            Conversation.objects.filter(lead=legacy_lead).exists()
        )

    def test_creates_new_contato_and_lead_with_internal_note(self):
        from apps.communications import services_imap

        self.assertFalse(
            Contato.objects.filter(email="novo@desconhecido.com").exists()
        )

        fake = FakeImapConn(messages=[
            (b"1", build_raw_message(
                from_addr="novo@desconhecido.com",
                from_name="Pessoa Nova",
                message_id="<new@x>",
            )),
        ])
        with patch.object(services_imap, "_open_connection", return_value=fake):
            result = services_imap.poll_inbox_for_empresa(self.empresa)

        self.assertEqual(result["ingested"], 1)
        new_contato = Contato.objects.get(email="novo@desconhecido.com")
        self.assertEqual(new_contato.empresa, self.empresa)
        new_lead = Lead.objects.get(contato=new_contato)
        self.assertEqual(new_lead.email, "novo@desconhecido.com")

        # Verifica nota interna automática
        conv = Conversation.objects.get(lead=new_lead)
        note = conv.messages.filter(
            channel=ConversationMessage.Channel.INTERNAL_NOTE,
        ).first()
        self.assertIsNotNone(note)
        self.assertIn("Lead criado automaticamente", note.content)
        self.assertIn("novo@desconhecido.com", note.content)


# ----------------------------------------------------------------------------
# 5. Failure isolation entre tenants
# ----------------------------------------------------------------------------


class FailureIsolationTests(TestCase):
    def setUp(self):
        cache.clear()
        # Empresa A (vai falhar)
        self.empresa_a = create_test_empresa("Empresa A", "empresa-a")
        create_test_user("a@t.com", "A", self.empresa_a)
        self.cfg_a = EmpresaEmailConfig.objects.create(
            empresa=self.empresa_a,
            host="smtp.a", port=587, username="a@a.com",
            from_email="a@a.com", from_name="A", is_active=True,
            imap_host="imap.a", imap_port=993, imap_use_ssl=True,
            imap_folder="INBOX", imap_active=True,
        )
        self.cfg_a.set_password("p1")
        self.cfg_a.save()

        # Empresa B (vai funcionar)
        self.empresa_b = create_test_empresa("Empresa B", "empresa-b")
        create_test_user("b@t.com", "B", self.empresa_b)
        self.cfg_b = EmpresaEmailConfig.objects.create(
            empresa=self.empresa_b,
            host="smtp.b", port=587, username="b@b.com",
            from_email="b@b.com", from_name="B", is_active=True,
            imap_host="imap.b", imap_port=993, imap_use_ssl=True,
            imap_folder="INBOX", imap_active=True,
        )
        self.cfg_b.set_password("p2")
        self.cfg_b.save()

    def test_failure_in_a_does_not_affect_b(self):
        from apps.communications import services_imap
        import imaplib

        def fake_open(cfg):
            if cfg.empresa_id == self.empresa_a.pk:
                raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
            # B: retorna fake conn com 1 mensagem
            return FakeImapConn(messages=[
                (b"1", build_raw_message(
                    from_addr="x@b.com",
                    message_id="<b-ok@x>",
                )),
            ])

        with patch.object(services_imap, "_open_connection", side_effect=fake_open):
            summary = services_imap.poll_all_inboxes()

        self.assertEqual(summary["polled"], 2)
        # Status A: falhou
        self.cfg_a.refresh_from_db()
        self.assertFalse(self.cfg_a.imap_last_poll_ok)
        self.assertIn("AUTHENTICATIONFAILED", self.cfg_a.imap_last_poll_error)
        self.assertIsNotNone(self.cfg_a.imap_last_poll_at)
        # Status B: sucesso
        self.cfg_b.refresh_from_db()
        self.assertTrue(self.cfg_b.imap_last_poll_ok)
        # B ingeriu sua mensagem
        self.assertTrue(
            ConversationMessage.objects.filter(
                conversation__empresa=self.empresa_b,
                channel="email",
            ).exists()
        )


# ----------------------------------------------------------------------------
# 6. Lock per-tenant
# ----------------------------------------------------------------------------


class LockTests(ImapBaseTest):
    def test_skipped_when_lock_held(self):
        from apps.communications import services_imap

        # Simula outro worker já segurando o lock
        cache.set(
            f"imap-poll-empresa-{self.empresa.pk}",
            "1",
            timeout=120,
        )

        with patch.object(services_imap, "_open_connection") as mock_open:
            result = services_imap.poll_inbox_for_empresa(self.empresa)

        self.assertTrue(result["skipped_lock"])
        # NÃO deve ter tentado conectar
        mock_open.assert_not_called()


# ----------------------------------------------------------------------------
# 7. Cap max_messages
# ----------------------------------------------------------------------------


class CapTests(ImapBaseTest):
    def test_respects_max_messages_limit(self):
        from apps.communications import services_imap

        # 100 mensagens disponíveis
        messages = []
        for i in range(100):
            messages.append((
                f"{i + 1}".encode(),
                build_raw_message(
                    from_addr=f"u{i}@x.com",
                    message_id=f"<cap-{i}@x>",
                ),
            ))
        fake = FakeImapConn(messages=messages)

        with patch.object(services_imap, "_open_connection", return_value=fake):
            result = services_imap.poll_inbox_for_empresa(
                self.empresa, max_messages=10,
            )

        # Limita a 10
        self.assertEqual(result["fetched"], 10)
        self.assertEqual(result["ingested"], 10)
        # Marcou Seen só nas 10 processadas
        self.assertEqual(len(fake.seen_uids), 10)


# ----------------------------------------------------------------------------
# 8. \Seen apenas após commit DB
# ----------------------------------------------------------------------------


class SeenOnlyAfterCommitTests(ImapBaseTest):
    def test_record_inbound_failure_does_not_mark_seen(self):
        from apps.communications import services_imap
        # IMPORTANTE: captura a função REAL ANTES de patchear (evita recursion).
        from apps.communications.services import record_inbound as real_ri

        fake = FakeImapConn(messages=[
            (b"1", build_raw_message(
                from_addr="erro@x.com",
                message_id="<fail@x>",
            )),
            (b"2", build_raw_message(
                from_addr="ok@x.com",
                message_id="<ok@x>",
            )),
        ])

        def flaky_record_inbound(**kwargs):
            if kwargs.get("sender_external_id") == "erro@x.com":
                raise RuntimeError("simulated DB write failure")
            return real_ri(**kwargs)

        with patch.object(services_imap, "_open_connection", return_value=fake), \
             patch(
                 "apps.communications.services.record_inbound",
                 side_effect=flaky_record_inbound,
             ):
            result = services_imap.poll_inbox_for_empresa(self.empresa)

        # Mensagem 1 falhou: NÃO marcou seen (próximo poll re-tenta)
        self.assertNotIn(b"1", fake.seen_uids)
        # Mensagem 2 sucesso: marcou seen
        self.assertIn(b"2", fake.seen_uids)
        # Sumário: 1 erro registrado, 1 ingerida
        self.assertEqual(result["ingested"], 1)
        self.assertGreaterEqual(len(result["errors"]), 1)


# ----------------------------------------------------------------------------
# 9. Status persistido em sucesso e falha
# ----------------------------------------------------------------------------


class StatusPersistenceTests(ImapBaseTest):
    def test_success_updates_last_poll_ok(self):
        from apps.communications import services_imap

        fake = FakeImapConn(messages=[])
        with patch.object(services_imap, "_open_connection", return_value=fake):
            services_imap.poll_inbox_for_empresa(self.empresa)

        self.cfg.refresh_from_db()
        self.assertTrue(self.cfg.imap_last_poll_ok)
        self.assertEqual(self.cfg.imap_last_poll_error, "")
        self.assertIsNotNone(self.cfg.imap_last_poll_at)

    def test_failure_updates_last_poll_error(self):
        from apps.communications import services_imap
        import imaplib

        with patch.object(
            services_imap, "_open_connection",
            side_effect=imaplib.IMAP4.error("AUTH FAILURE"),
        ):
            services_imap.poll_inbox_for_empresa(self.empresa)

        self.cfg.refresh_from_db()
        self.assertFalse(self.cfg.imap_last_poll_ok)
        self.assertIn("AUTH FAILURE", self.cfg.imap_last_poll_error)
        self.assertIsNotNone(self.cfg.imap_last_poll_at)


# ----------------------------------------------------------------------------
# 10. Endpoint de teste de conexão
# ----------------------------------------------------------------------------


class ImapTestEndpointTests(ImapBaseTest):
    def test_imap_test_endpoint_success(self):
        from apps.communications import services_imap

        fake = FakeImapConn(messages=[
            (b"1", build_raw_message(message_id="<e1@x>")),
        ])

        self.client.force_login(self.user)
        with patch.object(
            services_imap, "_open_connection", return_value=fake,
        ):
            resp = self.client.post(
                reverse("settings_app:email_imap_test"),
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Conectado", resp.content)
        # Status atualizado
        self.cfg.refresh_from_db()
        self.assertTrue(self.cfg.imap_last_poll_ok)
        # IMPORTANTE: não deve ter marcado Seen
        self.assertEqual(fake.seen_uids, [])

    def test_imap_test_endpoint_failure(self):
        from apps.communications import services_imap
        import imaplib

        self.client.force_login(self.user)
        with patch.object(
            services_imap, "_open_connection",
            side_effect=imaplib.IMAP4.error("BAD CREDENTIALS"),
        ):
            resp = self.client.post(
                reverse("settings_app:email_imap_test"),
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Falhou", resp.content)
        self.assertIn(b"BAD CREDENTIALS", resp.content)
        # Status persistido como falha
        self.cfg.refresh_from_db()
        self.assertFalse(self.cfg.imap_last_poll_ok)

    def test_imap_test_endpoint_without_config(self):
        # Sem imap_host configurado
        self.cfg.imap_host = ""
        self.cfg.save()

        self.client.force_login(self.user)
        resp = self.client.post(reverse("settings_app:email_imap_test"))
        self.assertEqual(resp.status_code, 400)
