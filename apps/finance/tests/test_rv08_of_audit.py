"""RV08 — Regressões do pente fino (Open Finance / CSV)."""
from decimal import Decimal

from django.test import SimpleTestCase

from apps.finance.open_finance import parse_csv


class CsvParserAuditTests(SimpleTestCase):
    def test_comma_delimited_comma_decimal_row_is_skipped_not_corrupted(self):
        """Antes: '1500,50' com vírgula-delimitador virava 1500 (corrupção).
        Agora a linha ambígua é pulada em vez de gravar valor errado."""
        rows = parse_csv("data,descricao,valor\n2026-01-10,Servico,1500,50\n")
        self.assertEqual(rows, [])

    def test_semicolon_brazilian_ok(self):
        rows = parse_csv("data;descricao;valor\n2026-01-10;Servico;1500,50\n")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], Decimal("1500.50"))

    def test_external_id_stable_across_files(self):
        """O id sem id-do-banco deve ser estável entre extratos diferentes
        (mesma transação, outras linhas ao redor) — antes usava a posição."""
        a = parse_csv("data;descricao;valor\n2026-01-10;X;100,00\n")
        b = parse_csv(
            "data;descricao;valor\n2026-02-01;Y;200,00\n2026-01-10;X;100,00\n"
        )
        ax = next(r for r in a if r["description"] == "X")
        bx = next(r for r in b if r["description"] == "X")
        self.assertEqual(ax["external_id"], bx["external_id"])
