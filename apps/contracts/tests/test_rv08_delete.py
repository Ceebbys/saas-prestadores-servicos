"""RV08 (1.1) — Exclusão de contratos (Rascunho/Cancelado) com confirmação."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.automation.models import AutomationLog
from apps.contracts.models import Contract
from apps.core.tests.helpers import (
    create_test_empresa,
    create_test_user,
)
from apps.crm.models import Lead
from apps.finance.models import FinancialEntry


def _contract(empresa, lead, status=Contract.Status.DRAFT):
    return Contract.objects.create(
        empresa=empresa, lead=lead, title="Contrato X",
        value=Decimal("1000"), status=status,
    )


class ContractDeleteRV08Tests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("c@t.com", "C", self.empresa)
        self.client.force_login(self.user)
        self.lead = Lead.objects.create(empresa=self.empresa, name="Lead X")

    def test_get_returns_confirmation_modal(self):
        c = _contract(self.empresa, self.lead)
        resp = self.client.get(reverse("contracts:delete", args=[c.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Excluir contrato")
        self.assertContains(resp, "delete-contract-form")

    def test_draft_is_soft_deleted(self):
        c = _contract(self.empresa, self.lead, Contract.Status.DRAFT)
        resp = self.client.post(reverse("contracts:delete", args=[c.pk]))
        self.assertIn(resp.status_code, (302, 303))
        # Sumiu do manager padrão, mas continua em all_objects (lixeira)
        self.assertFalse(Contract.objects.filter(pk=c.pk).exists())
        c_all = Contract.all_objects.get(pk=c.pk)
        self.assertIsNotNone(c_all.deleted_at)
        self.assertTrue(
            AutomationLog.objects.filter(
                empresa=self.empresa,
                action=AutomationLog.Action.CONTRACT_DELETED,
                entity_id=c.pk,
            ).exists()
        )

    def test_cancelled_is_deletable(self):
        c = _contract(self.empresa, self.lead, Contract.Status.CANCELLED)
        self.client.post(reverse("contracts:delete", args=[c.pk]))
        self.assertFalse(Contract.objects.filter(pk=c.pk).exists())

    def test_active_contract_is_protected(self):
        c = _contract(self.empresa, self.lead, Contract.Status.ACTIVE)
        resp = self.client.post(reverse("contracts:delete", args=[c.pk]))
        self.assertIn(resp.status_code, (302, 303))
        # Não foi excluído — status não permitido
        self.assertTrue(Contract.objects.filter(pk=c.pk).exists())

    def test_cascade_deletes_pending_entries(self):
        c = _contract(self.empresa, self.lead, Contract.Status.CANCELLED)
        entry = FinancialEntry.objects.create(
            empresa=self.empresa, type=FinancialEntry.Type.INCOME,
            description="Parcela 1", amount=Decimal("500"),
            date="2026-01-10", status=FinancialEntry.Status.PENDING,
            related_contract=c,
        )
        self.client.post(
            reverse("contracts:delete", args=[c.pk]),
            data={"delete_entries": "1"},
        )
        self.assertFalse(FinancialEntry.objects.filter(pk=entry.pk).exists())

    def test_restore_from_trash(self):
        c = _contract(self.empresa, self.lead, Contract.Status.DRAFT)
        c.delete()  # soft
        self.assertFalse(Contract.objects.filter(pk=c.pk).exists())
        resp = self.client.post(reverse("contracts:restore", args=[c.pk]))
        self.assertIn(resp.status_code, (302, 303))
        self.assertTrue(Contract.objects.filter(pk=c.pk).exists())
