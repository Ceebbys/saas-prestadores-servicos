"""RV08 (6.1) — Open Finance: parsers, import idempotente, classificação."""
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.finance.models import (
    BankConnection,
    FinancialCategory,
    FinancialEntry,
    ImportedTransaction,
)
from apps.finance.open_finance import (
    classify_transaction,
    import_transactions,
    parse_csv,
    parse_ofx,
)


class OpenFinanceParsersTests(TestCase):
    def test_parse_csv_semicolon_brazilian(self):
        content = (
            "data;descricao;valor\n"
            "2026-01-10;PIX Cliente;1500,00\n"
            "2026-01-11;Tarifa mensal;-39,90\n"
        )
        rows = parse_csv(content)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["amount"], Decimal("1500.00"))
        self.assertEqual(rows[1]["amount"], Decimal("-39.90"))

    def test_parse_csv_comma_us(self):
        content = "date,description,amount\n2026-02-01,Service,3200.00\n"
        rows = parse_csv(content)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], Decimal("3200.00"))

    def test_parse_ofx(self):
        content = """
        <OFX><BANKMSGSRSV1><STMTTRNRS><BANKTRANLIST>
          <STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260115000000<TRNAMT>1500.00
            <FITID>ABC123<MEMO>Deposito cliente</STMTTRN>
          <STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260116<TRNAMT>-50.00
            <FITID>ABC124<MEMO>Tarifa</STMTTRN>
        </BANKTRANLIST></STMTTRNRS></BANKMSGSRSV1></OFX>
        """
        rows = parse_ofx(content)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["external_id"], "ABC123")
        self.assertEqual(rows[0]["amount"], Decimal("1500.00"))
        self.assertEqual(rows[0]["date"].isoformat(), "2026-01-15")


class OpenFinanceServiceTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv08-of")
        self.user = create_test_user("of@t.com", "OF", self.empresa)

    def _rows(self):
        return [
            {"external_id": "x1", "date": "2026-01-10", "amount": Decimal("1500.00"),
             "description": "Receita", "direction": "credit"},
            {"external_id": "x2", "date": "2026-01-11", "amount": Decimal("-40.00"),
             "description": "Despesa"},
        ]

    def test_import_is_idempotent(self):
        r1 = import_transactions(self.empresa, self._rows())
        self.assertEqual(r1["created"], 2)
        r2 = import_transactions(self.empresa, self._rows())
        self.assertEqual(r2["created"], 0)
        self.assertEqual(
            ImportedTransaction.objects.filter(empresa=self.empresa).count(), 2,
        )

    def test_direction_inferred_from_sign(self):
        import_transactions(self.empresa, self._rows())
        debit = ImportedTransaction.objects.get(empresa=self.empresa, external_id="x2")
        self.assertEqual(debit.direction, "debit")
        self.assertEqual(debit.amount, Decimal("40.00"))  # valor absoluto

    def test_classify_creates_paid_entry(self):
        import_transactions(self.empresa, self._rows())
        txn = ImportedTransaction.objects.get(empresa=self.empresa, external_id="x1")
        cat = FinancialCategory.objects.create(
            empresa=self.empresa, name="Serviços", type=FinancialCategory.Type.INCOME,
        )
        entry = classify_transaction(
            txn, entry_type=FinancialEntry.Type.INCOME, category=cat,
        )
        self.assertEqual(entry.type, FinancialEntry.Type.INCOME)
        self.assertEqual(entry.amount, Decimal("1500.00"))
        self.assertEqual(entry.status, FinancialEntry.Status.PAID)
        self.assertIsNotNone(entry.paid_date)
        txn.refresh_from_db()
        self.assertEqual(txn.classification_status, ImportedTransaction.Status.CLASSIFIED)
        self.assertEqual(txn.classified_entry_id, entry.pk)

    def test_classify_is_idempotent(self):
        import_transactions(self.empresa, self._rows())
        txn = ImportedTransaction.objects.get(empresa=self.empresa, external_id="x1")
        e1 = classify_transaction(txn, entry_type=FinancialEntry.Type.INCOME)
        e2 = classify_transaction(txn, entry_type=FinancialEntry.Type.INCOME)
        self.assertEqual(e1.pk, e2.pk)
        self.assertEqual(FinancialEntry.objects.filter(empresa=self.empresa).count(), 1)


class OpenFinanceViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv08-ofv")
        self.user = create_test_user("ofv@t.com", "OFV", self.empresa)
        self.client.force_login(self.user)

    def test_connect_sandbox_imports_demo(self):
        resp = self.client.post(reverse("finance:open_finance_connect_sandbox"))
        self.assertIn(resp.status_code, (302, 303))
        self.assertTrue(
            BankConnection.objects.filter(
                empresa=self.empresa, provider=BankConnection.Provider.SANDBOX,
            ).exists()
        )
        self.assertTrue(
            ImportedTransaction.objects.filter(empresa=self.empresa).exists()
        )

    def test_import_csv_upload(self):
        csv_bytes = (
            "data;descricao;valor\n2026-03-01;PIX recebido;2500,00\n"
        ).encode("utf-8")
        upload = SimpleUploadedFile("extrato.csv", csv_bytes, content_type="text/csv")
        resp = self.client.post(
            reverse("finance:open_finance_import"), {"file": upload},
        )
        self.assertIn(resp.status_code, (302, 303))
        self.assertEqual(
            ImportedTransaction.objects.filter(empresa=self.empresa).count(), 1,
        )

    def test_classify_view_creates_entry(self):
        import_transactions(
            self.empresa,
            [{"external_id": "v1", "date": "2026-01-10",
              "amount": Decimal("900.00"), "direction": "credit",
              "description": "Entrada"}],
        )
        txn = ImportedTransaction.objects.get(empresa=self.empresa, external_id="v1")
        resp = self.client.post(
            reverse("finance:open_finance_classify", args=[txn.pk]),
            {"type": "income"},
        )
        self.assertIn(resp.status_code, (302, 303))
        txn.refresh_from_db()
        self.assertEqual(txn.classification_status, ImportedTransaction.Status.CLASSIFIED)
        self.assertEqual(FinancialEntry.objects.filter(empresa=self.empresa).count(), 1)

    def test_page_renders(self):
        resp = self.client.get(reverse("finance:open_finance"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Open Finance")
