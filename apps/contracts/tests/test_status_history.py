"""Testes do RV05-F — ContractStatusHistory + signals."""
from decimal import Decimal

from django.test import TestCase

from apps.contracts.models import Contract, ContractStatusHistory
from apps.crm.models import Lead
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


def _make_contract(empresa, **kwargs):
    create_pipeline_for_empresa(empresa)
    lead = Lead.objects.create(empresa=empresa, name="X", email="a@b.com")
    kwargs.setdefault("title", "Contrato T")
    kwargs.setdefault("value", Decimal("1000"))
    return Contract.objects.create(empresa=empresa, lead=lead, **kwargs)


class ContractStatusHistorySignalTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("h@t.com", "H", self.empresa)

    def test_creation_records_initial_history(self):
        c = _make_contract(self.empresa)
        hist = ContractStatusHistory.objects.filter(contract=c)
        self.assertEqual(hist.count(), 1)
        first = hist.first()
        self.assertEqual(first.from_status, "")
        self.assertEqual(first.to_status, Contract.Status.DRAFT)

    def test_status_transition_creates_history_row(self):
        c = _make_contract(self.empresa)
        self.assertEqual(ContractStatusHistory.objects.filter(contract=c).count(), 1)
        c.status = Contract.Status.SENT
        c.save()
        self.assertEqual(ContractStatusHistory.objects.filter(contract=c).count(), 2)
        last = ContractStatusHistory.objects.filter(contract=c).order_by("-created_at").first()
        self.assertEqual(last.from_status, Contract.Status.DRAFT)
        self.assertEqual(last.to_status, Contract.Status.SENT)

    def test_save_without_status_change_doesnt_create_row(self):
        c = _make_contract(self.empresa)
        c.title = "Novo Título"
        c.save()
        # Apenas a criação inicial fica registrada
        self.assertEqual(ContractStatusHistory.objects.filter(contract=c).count(), 1)

    def test_changed_by_attached_when_view_sets_attr(self):
        c = _make_contract(self.empresa)
        c.status = Contract.Status.SENT
        c._status_changed_by = self.user
        c._status_change_note = "Enviado por e-mail"
        c.save()
        last = ContractStatusHistory.objects.filter(contract=c).order_by("-created_at").first()
        self.assertEqual(last.changed_by, self.user)
        self.assertEqual(last.note, "Enviado por e-mail")

    def test_changed_by_none_when_attr_absent(self):
        c = _make_contract(self.empresa)
        c.status = Contract.Status.SENT
        c.save()
        last = ContractStatusHistory.objects.filter(contract=c).order_by("-created_at").first()
        self.assertIsNone(last.changed_by)

    def test_str_representation(self):
        c = _make_contract(self.empresa)
        c.status = Contract.Status.SENT
        c.save()
        last = ContractStatusHistory.objects.filter(contract=c).order_by("-created_at").first()
        self.assertIn(c.number, str(last))
        self.assertIn("draft", str(last))
        self.assertIn("sent", str(last))


class ContractStatusViewIntegrationTests(TestCase):
    """Garante que ContractStatusView dispara o signal com autor."""

    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("v@t.com", "V", self.empresa)
        self.client.force_login(self.user)

    def test_view_status_change_records_user(self):
        from django.urls import reverse
        c = _make_contract(self.empresa)
        c.status = Contract.Status.SENT
        c.save()
        # POST view para mover SENT → SIGNED
        url = reverse("contracts:status", args=[c.pk])
        resp = self.client.post(url, data={"status": Contract.Status.SIGNED})
        self.assertIn(resp.status_code, (200, 302))
        c.refresh_from_db()
        self.assertEqual(c.status, Contract.Status.SIGNED)
        # Última entrada de histórico deve ter o user
        last = ContractStatusHistory.objects.filter(contract=c).order_by("-created_at").first()
        self.assertEqual(last.from_status, Contract.Status.SENT)
        self.assertEqual(last.to_status, Contract.Status.SIGNED)
        self.assertEqual(last.changed_by, self.user)
