"""RV05-H — ContractFromProposalView popula campos rich novos (body/terms/introduction).

Antes do RV05-H, populava só o campo `content` legado, deixando `body` vazio
e o contrato dependendo do dual-read no render.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.contracts.models import Contract
from apps.crm.models import Lead
from apps.proposals.models import Proposal
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


class ContractFromProposalInitialTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("fp@t.com", "FP", self.empresa)
        create_pipeline_for_empresa(self.empresa)
        self.client.force_login(self.user)
        self.lead = Lead.objects.create(
            empresa=self.empresa, name="L", email="l@l.com",
        )
        self.proposal = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead,
            title="Prop Origem",
            introduction="<p>Intro rich da proposta</p>",
            body="<p><strong>Corpo</strong> rich da proposta</p>",
            terms="<p>Termos rich da proposta</p>",
            discount_percent=Decimal("0"),
        )

    def test_initial_populates_body_not_content(self):
        """GET na view → form com `body` preenchido (novo), não `content` (legado)."""
        url = reverse("contracts:from_proposal", args=[self.proposal.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # Body deve estar no HTML do form (campo rich)
        self.assertContains(resp, "Corpo")
        # Terms também
        self.assertContains(resp, "Termos rich")
        # Introduction também
        self.assertContains(resp, "Intro rich")

    def test_initial_body_sanitized_against_xss(self):
        """Mesmo se proposta tem conteúdo suspeito, o initial deve sanitizar."""
        evil = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead,
            title="Evil",
            body="<p>OK</p><script>alert(1)</script>",
            discount_percent=Decimal("0"),
        )
        url = reverse("contracts:from_proposal", args=[evil.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # Script removido pelo sanitizer
        self.assertNotContains(resp, "<script>alert(1)</script>")

    def test_initial_skips_empty_fields(self):
        """Proposta sem terms/intro → contrato não recebe esses campos."""
        empty = Proposal.objects.create(
            empresa=self.empresa, lead=self.lead,
            title="Empty Origem",
            body="<p>só body</p>",
            terms="",
            introduction="",
            discount_percent=Decimal("0"),
        )
        url = reverse("contracts:from_proposal", args=[empty.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "só body")
