"""RV08 (5.3) — Envio automático de propostas pelo chatbot voltou a funcionar.

Bug raiz: `_create_proposal_from_template` passava `content=` para
`Proposal.objects.create()`, mas `Proposal` não tem esse campo (é `body`),
levantando TypeError capturado pelo dispatcher como "Erro executando ação…".
"""
from decimal import Decimal

from django.test import TestCase

from apps.chatbot.action_handlers import _create_proposal_from_template
from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.crm.models import Lead
from apps.operations.models import ServiceType
from apps.proposals.models import Proposal, ProposalTemplate
from apps.proposals.services.whatsapp import _build_public_link


class SendProposalRV08Tests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("c@t.com", "C", self.empresa)
        self.lead = Lead.objects.create(empresa=self.empresa, name="Lead X")

    def test_auto_create_proposal_does_not_raise(self):
        """O bug: criava com content= e estourava TypeError."""
        proposal = _create_proposal_from_template(
            self.empresa, self.lead, None, {},
        )
        self.assertIsNotNone(proposal.pk)
        self.assertEqual(proposal.status, Proposal.Status.DRAFT)
        self.assertEqual(proposal.lead, self.lead)

    def test_template_content_maps_to_body(self):
        ProposalTemplate.objects.create(
            empresa=self.empresa, name="Padrão",
            content="<p>Olá, segue a proposta</p>", is_default=True,
        )
        proposal = _create_proposal_from_template(
            self.empresa, self.lead, None, {},
        )
        self.assertIn("segue a proposta", proposal.body)

    def test_servico_snapshot_adds_priced_item(self):
        servico = ServiceType.objects.create(
            empresa=self.empresa, name="Topografia",
            default_price=Decimal("1500.00"),
        )
        lead_data = {
            "servico_snapshot": {
                "id": servico.pk,
                "name": "Topografia",
                "default_price": "1500.00",
            }
        }
        proposal = _create_proposal_from_template(
            self.empresa, self.lead, None, lead_data,
        )
        self.assertEqual(proposal.items.count(), 1)
        self.assertEqual(proposal.total, Decimal("1500.00"))
        self.assertEqual(proposal.servico_id, servico.pk)

    def test_public_link_is_absolute_without_request(self):
        proposal = _create_proposal_from_template(
            self.empresa, self.lead, None, {},
        )
        link = _build_public_link(proposal, None)
        self.assertTrue(link.startswith("http"), link)
        self.assertIn(f"/p/{proposal.public_token}/", link)
