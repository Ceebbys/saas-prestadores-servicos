"""Testes do lazy-lead em _mirror_to_inbox.

Garante que mensagens WhatsApp aparecem na inbox unificada desde o
PRIMEIRO turno (antes do bot coletar nome/email do cliente). Antes deste
fix, mensagens eram perdidas porque o Lead só era criado no fim do fluxo
em `_create_lead_action`.

Também valida que `create_lead_from_chatbot` hidrata o Lead lazy
existente em vez de criar duplicata, e que o `external_ref` casa entre
as duas pontas.
"""
from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import Empresa
from apps.chatbot.models import ChatbotFlow, ChatbotSession
from apps.chatbot.whatsapp import (
    _mirror_inbound_no_bot,
    _mirror_to_inbox,
    _resolve_or_create_lead_lazy,
    parse_evolution_webhook,
    parse_evolution_webhook_outbound,
)
from apps.communications.models import (
    Conversation,
    ConversationMessage,
)
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead


def _make_flow(empresa, name="Test Flow"):
    """Cria flow mínimo de teste."""
    return ChatbotFlow.objects.create(
        empresa=empresa,
        name=name,
        is_active=True,
        welcome_message="Olá!",
    )


class EvolutionParserTests(TestCase):
    """Garante que ambos formatos de evento são aceitos.

    Evolution API v1: 'messages.upsert' (lowercase + dot)
    Evolution API v2: 'MESSAGES_UPSERT' (uppercase + underscore)
    """

    BASE_INBOUND = {
        "instance": "test-instance",
        "data": {
            "key": {
                "fromMe": False,
                "remoteJid": "5511987654321@s.whatsapp.net",
            },
            "message": {"conversation": "Olá"},
        },
    }
    BASE_OUTBOUND = {
        "instance": "test-instance",
        "data": {
            "key": {
                "fromMe": True,
                "remoteJid": "5511987654321@s.whatsapp.net",
            },
            "message": {"conversation": "Resposta do operador"},
        },
    }

    def test_inbound_accepts_v1_event_lowercase_dot(self):
        body = {**self.BASE_INBOUND, "event": "messages.upsert"}
        result = parse_evolution_webhook(body)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "5511987654321")
        self.assertEqual(result[1], "Olá")

    def test_inbound_accepts_v2_event_uppercase_underscore(self):
        body = {**self.BASE_INBOUND, "event": "MESSAGES_UPSERT"}
        result = parse_evolution_webhook(body)
        self.assertIsNotNone(result, "Evolution v2 envia MESSAGES_UPSERT")
        self.assertEqual(result[0], "5511987654321")

    def test_inbound_rejects_other_events(self):
        for event in ["CONNECTION_UPDATE", "connection.update", "qrcode.updated", ""]:
            body = {**self.BASE_INBOUND, "event": event}
            self.assertIsNone(parse_evolution_webhook(body), f"event={event!r} deveria ser ignorado")

    def test_outbound_accepts_v2_event(self):
        body = {**self.BASE_OUTBOUND, "event": "MESSAGES_UPSERT"}
        result = parse_evolution_webhook_outbound(body)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "5511987654321")
        self.assertEqual(result[1], "Resposta do operador")

    def test_outbound_skips_api_source(self):
        # Mensagens que NÓS enviamos via Evolution API (source=api) NÃO devem
        # ser ré-gravadas — `send_whatsapp` já gravou.
        body = {
            **self.BASE_OUTBOUND,
            "event": "MESSAGES_UPSERT",
        }
        body["data"]["source"] = "api"
        result = parse_evolution_webhook_outbound(body)
        self.assertIsNone(result)


class LazyLeadResolutionTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("u@t.com", "U", self.empresa)
        self.flow = _make_flow(self.empresa)

    def test_creates_lazy_lead_when_session_has_no_lead(self):
        """Primeiro contato: session existe mas sem lead → cria lazy."""
        session = ChatbotSession.objects.create(
            flow=self.flow,
            sender_id="5511999990001",
            channel="whatsapp",
            status=ChatbotSession.Status.ACTIVE,
        )
        self.assertEqual(Lead.objects.count(), 0)

        lead = _resolve_or_create_lead_lazy(
            self.flow, "5511999990001", session=session,
        )

        self.assertIsNotNone(lead)
        self.assertEqual(lead.empresa, self.empresa)
        self.assertEqual(lead.phone, "5511999990001")
        self.assertEqual(lead.source, Lead.Source.WHATSAPP)
        self.assertEqual(lead.external_ref, str(session.session_key))
        # Lead vinculado à session
        session.refresh_from_db()
        self.assertEqual(session.lead_id, lead.pk)

    def test_returns_existing_session_lead_without_creating(self):
        """Se session já tem lead, retorna sem criar novo."""
        existing_lead = Lead.objects.create(
            empresa=self.empresa, name="Already Here", phone="5511999990002",
        )
        session = ChatbotSession.objects.create(
            flow=self.flow,
            sender_id="5511999990002",
            channel="whatsapp",
            status=ChatbotSession.Status.ACTIVE,
            lead=existing_lead,
        )
        count_before = Lead.objects.count()
        lead = _resolve_or_create_lead_lazy(
            self.flow, "5511999990002", session=session,
        )
        self.assertEqual(lead, existing_lead)
        self.assertEqual(Lead.objects.count(), count_before)

    def test_resolves_existing_lead_by_phone_match(self):
        """Cliente voltando: existe lead com mesmo phone → re-engaja."""
        existing_lead = Lead.objects.create(
            empresa=self.empresa, name="Returning", phone="5511999990003",
        )
        # Session NOVA (lead_id None) mas com mesmo sender_id
        session = ChatbotSession.objects.create(
            flow=self.flow,
            sender_id="5511999990003",
            channel="whatsapp",
            status=ChatbotSession.Status.ACTIVE,
        )
        lead = _resolve_or_create_lead_lazy(
            self.flow, "5511999990003", session=session,
        )
        # Reutiliza lead existente, vincula à session
        self.assertEqual(lead, existing_lead)
        session.refresh_from_db()
        self.assertEqual(session.lead_id, existing_lead.pk)

    def test_cross_tenant_blocked(self):
        """session.lead de OUTRA empresa → retorna None (log error)."""
        other_empresa = create_test_empresa("Other", "other")
        rogue_lead = Lead.objects.create(
            empresa=other_empresa, name="Rogue", phone="9999",
        )
        session = ChatbotSession.objects.create(
            flow=self.flow,
            sender_id="9999",
            channel="whatsapp",
            status=ChatbotSession.Status.ACTIVE,
            lead=rogue_lead,
        )
        lead = _resolve_or_create_lead_lazy(self.flow, "9999", session=session)
        self.assertIsNone(lead)

    def test_no_digits_returns_none(self):
        """sender_id sem dígitos → não consegue criar lead."""
        session = ChatbotSession.objects.create(
            flow=self.flow,
            sender_id="@invalid",
            channel="whatsapp",
            status=ChatbotSession.Status.ACTIVE,
        )
        lead = _resolve_or_create_lead_lazy(
            self.flow, "@invalid", session=session,
        )
        self.assertIsNone(lead)


class MirrorToInboxTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        create_test_user("m@t.com", "M", self.empresa)
        self.flow = _make_flow(self.empresa)

    def test_mirror_creates_conversation_on_first_inbound(self):
        """E2E: primeira msg WhatsApp gera Conversation + 2 mensagens (in+out bot)."""
        session = ChatbotSession.objects.create(
            flow=self.flow,
            sender_id="5511777777777",
            channel="whatsapp",
            status=ChatbotSession.Status.ACTIVE,
        )

        _mirror_to_inbox(
            self.flow,
            "5511777777777",
            inbound_text="Olá, quero orçamento",
            outbound_text="Bot: Claro! Qual seu nome?",
            session=session,
        )

        # Conversation criada
        self.assertEqual(Conversation.objects.count(), 1)
        conv = Conversation.objects.first()
        self.assertEqual(conv.empresa, self.empresa)
        self.assertEqual(conv.lead.phone, "5511777777777")
        # 2 mensagens: 1 inbound + 1 outbound do bot
        msgs = conv.messages.order_by("created_at")
        self.assertEqual(msgs.count(), 2)
        self.assertEqual(msgs[0].direction, ConversationMessage.Direction.INBOUND)
        self.assertEqual(msgs[0].content, "Olá, quero orçamento")
        self.assertEqual(msgs[1].direction, ConversationMessage.Direction.OUTBOUND)
        self.assertTrue(msgs[1].payload.get("sent_by_bot"))

    def test_mirror_reuses_lead_across_turns(self):
        """Múltiplas msgs na mesma session → única Conversation, várias msgs."""
        session = ChatbotSession.objects.create(
            flow=self.flow,
            sender_id="5511666666666",
            channel="whatsapp",
            status=ChatbotSession.Status.ACTIVE,
        )

        for i in range(3):
            _mirror_to_inbox(
                self.flow,
                "5511666666666",
                inbound_text=f"msg {i}",
                outbound_text=f"resposta {i}",
                session=session,
            )

        # Apenas 1 conversation, 1 lead
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(Lead.objects.count(), 1)
        # 6 mensagens (3 in + 3 out)
        conv = Conversation.objects.first()
        self.assertEqual(conv.messages.count(), 6)


class CreateLeadHydratesLazyTests(TestCase):
    """Quando _create_lead_action chama create_lead_from_chatbot, deve
    hidratar Lead lazy existente em vez de duplicar."""

    def setUp(self):
        self.empresa = create_test_empresa()
        self.flow = _make_flow(self.empresa)

    def test_lazy_lead_hydrated_at_flow_completion(self):
        from apps.automation.services import create_lead_from_chatbot

        # Simula lazy lead criado no primeiro turno
        session = ChatbotSession.objects.create(
            flow=self.flow,
            sender_id="5511555555555",
            channel="whatsapp",
            status=ChatbotSession.Status.ACTIVE,
        )
        lazy = _resolve_or_create_lead_lazy(
            self.flow, "5511555555555", session=session,
        )
        self.assertTrue(lazy.name.startswith("WhatsApp"))
        self.assertEqual(lazy.email, "")

        # Final do fluxo: bot coletou nome+email
        session_data = {
            "name": "João Silva",
            "email": "joao@cli.com",
            "phone": "5511555555555",
            "session_id": str(session.session_key),
        }
        result_lead = create_lead_from_chatbot(self.empresa, self.flow, session_data)

        # MESMO lead — não duplica!
        self.assertEqual(result_lead.pk, lazy.pk)
        # Campos hidratados
        result_lead.refresh_from_db()
        self.assertEqual(result_lead.name, "João Silva")
        self.assertEqual(result_lead.email, "joao@cli.com")
        # phone permanece (já estava setado pelo lazy)
        self.assertEqual(result_lead.phone, "5511555555555")
        # Lead único — não duplicou
        self.assertEqual(
            Lead.objects.filter(
                empresa=self.empresa, phone="5511555555555",
            ).count(),
            1,
        )

    def test_create_lead_does_not_overwrite_admin_filled_fields(self):
        """Se admin editou name manualmente, hidratação NÃO sobrescreve."""
        from apps.automation.services import create_lead_from_chatbot

        session = ChatbotSession.objects.create(
            flow=self.flow,
            sender_id="5511444444444",
            channel="whatsapp",
            status=ChatbotSession.Status.ACTIVE,
        )
        lazy = _resolve_or_create_lead_lazy(
            self.flow, "5511444444444", session=session,
        )
        # Admin edita name antes do fim do fluxo
        lazy.name = "Nome Manual do Admin"
        lazy.save()

        session_data = {
            "name": "Coletado pelo Bot",
            "session_id": str(session.session_key),
        }
        create_lead_from_chatbot(self.empresa, self.flow, session_data)

        lazy.refresh_from_db()
        # Hidratação só toca campos que começam com "WhatsApp " ou vazios
        self.assertEqual(lazy.name, "Nome Manual do Admin")


class AutoCreateContatoTests(TestCase):
    """RV06 Item 4 — Quando WhatsApp recebe primeira msg, cria Contato também."""

    def setUp(self):
        self.empresa = create_test_empresa()
        self.flow = _make_flow(self.empresa)

    def test_lazy_lead_also_creates_contato(self):
        from apps.contacts.models import Contato
        from apps.crm.models import Lead

        # Primeira msg → resolve cria Lead E Contato vinculado
        sender = "5511987654321"
        # Session existente (criada por start_session) para passar ao resolver
        session = ChatbotSession.objects.create(
            flow=self.flow, sender_id=sender, channel="whatsapp",
            status=ChatbotSession.Status.ACTIVE,
        )
        before_contatos = Contato.objects.count()
        before_leads = Lead.objects.count()

        lead = _resolve_or_create_lead_lazy(
            self.flow, sender, session=session,
        )

        self.assertIsNotNone(lead)
        self.assertEqual(Lead.objects.count(), before_leads + 1)
        self.assertEqual(Contato.objects.count(), before_contatos + 1)
        # Lead.contato vinculado
        lead.refresh_from_db()
        self.assertIsNotNone(lead.contato_id)
        # Contato criado com phone e whatsapp
        contato = lead.contato
        self.assertEqual(contato.phone, sender)
        self.assertEqual(contato.whatsapp, sender)
        self.assertEqual(contato.empresa, self.empresa)
        self.assertEqual(contato.source, Contato.Source.WHATSAPP)

    def test_repeated_calls_reuse_contato(self):
        """Não duplica Contato quando mesmo número volta a mandar msg."""
        from apps.contacts.models import Contato

        sender = "5511944332211"
        s1 = ChatbotSession.objects.create(
            flow=self.flow, sender_id=sender, channel="whatsapp",
            status=ChatbotSession.Status.ACTIVE,
        )
        _resolve_or_create_lead_lazy(self.flow, sender, session=s1)
        before = Contato.objects.filter(empresa=self.empresa).count()

        # Segunda sessão do mesmo número
        s2 = ChatbotSession.objects.create(
            flow=self.flow, sender_id=sender, channel="whatsapp",
            status=ChatbotSession.Status.ACTIVE,
        )
        _resolve_or_create_lead_lazy(self.flow, sender, session=s2)
        # Mesma quantidade de Contatos
        self.assertEqual(
            Contato.objects.filter(empresa=self.empresa).count(), before,
        )

    def test_mirror_inbound_no_bot_also_creates_contato(self):
        """Tenant sem chatbot flow: ainda cria Lead + Contato."""
        from apps.contacts.models import Contato
        from apps.crm.models import Lead

        sender = "5511955667788"
        _mirror_inbound_no_bot(self.empresa, sender, "Olá")
        # Lead E Contato criados
        lead = Lead.objects.get(empresa=self.empresa, phone=sender)
        self.assertIsNotNone(lead.contato_id)
        contato = Contato.objects.get(empresa=self.empresa, phone=sender)
        self.assertEqual(contato.whatsapp, sender)

    def test_hydrate_lazy_lead_updates_contato_in_parallel(self):
        """Quando fluxo completa, Contato também é hidratado com name/email/cpf."""
        from apps.automation.services import create_lead_from_chatbot

        sender = "5511966554433"
        session = ChatbotSession.objects.create(
            flow=self.flow, sender_id=sender, channel="whatsapp",
            status=ChatbotSession.Status.ACTIVE,
        )
        lazy = _resolve_or_create_lead_lazy(self.flow, sender, session=session)
        # Antes da hidratação
        self.assertTrue(lazy.contato.name.startswith("WhatsApp"))
        self.assertEqual(lazy.contato.email, "")

        # Final do fluxo
        session_data = {
            "name": "Maria Silva",
            "email": "maria@x.com",
            "phone": sender,
            "session_id": str(session.session_key),
        }
        create_lead_from_chatbot(self.empresa, self.flow, session_data)

        lazy.refresh_from_db()
        # Lead hidratado
        self.assertEqual(lazy.name, "Maria Silva")
        # Contato hidratado em paralelo
        self.assertEqual(lazy.contato.name, "Maria Silva")
        self.assertEqual(lazy.contato.email, "maria@x.com")
