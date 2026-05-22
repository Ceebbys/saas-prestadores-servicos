"""Testes do matcher unificado de opções de menu (simulator + executor).

Bug reportado: usuário clica em quick-reply '1 Solicitar orçamento' no
simulador e bot responde 'Não entendi'. Solução: matcher tolerante a
múltiplos formatos de input. Cobertura exaustiva neste arquivo.
"""
from django.test import TestCase

from apps.chatbot.builder.services.menu_matcher import (
    MatchResult,
    match_menu_choice,
)


_OPTIONS = [
    {"label": "Solicitar orçamento", "handle_id": "opt_1"},
    {"label": "Ver serviços e preços", "handle_id": "opt_2"},
    {"label": "Acompanhar serviço", "handle_id": "opt_3"},
    {"label": "Falar com atendente / suporte", "handle_id": "opt_4"},
]


class MenuMatcherTests(TestCase):

    # ---- Match por número ----

    def test_pure_number(self):
        m = match_menu_choice(_OPTIONS, "1")
        self.assertEqual(m.handle_id, "opt_1")
        self.assertEqual(m.matched_by, "number")

    def test_pure_number_with_whitespace(self):
        m = match_menu_choice(_OPTIONS, "  2  ")
        self.assertEqual(m.handle_id, "opt_2")

    def test_out_of_range_number_returns_none(self):
        self.assertIsNone(match_menu_choice(_OPTIONS, "9"))

    def test_zero_returns_none(self):
        # 0 - 1 = -1, fora do range
        self.assertIsNone(match_menu_choice(_OPTIONS, "0"))

    # ---- Match por label ----

    def test_exact_label(self):
        m = match_menu_choice(_OPTIONS, "Solicitar orçamento")
        self.assertEqual(m.handle_id, "opt_1")
        self.assertEqual(m.matched_by, "label")

    def test_lowercase_label(self):
        m = match_menu_choice(_OPTIONS, "solicitar orçamento")
        self.assertEqual(m.handle_id, "opt_1")

    def test_uppercase_label(self):
        m = match_menu_choice(_OPTIONS, "SOLICITAR ORÇAMENTO")
        self.assertEqual(m.handle_id, "opt_1")

    def test_label_without_accent(self):
        m = match_menu_choice(_OPTIONS, "solicitar orcamento")
        self.assertEqual(m.handle_id, "opt_1")

    # ---- Match por "N Label" (caso real do bug) ----

    def test_number_space_label(self):
        """O bug reportado: '1 Solicitar orçamento' deve casar."""
        m = match_menu_choice(_OPTIONS, "1 Solicitar orçamento")
        self.assertIsNotNone(m, "Bug do print: '1 Label' deve matchar")
        self.assertEqual(m.handle_id, "opt_1")
        self.assertEqual(m.matched_by, "number_with_label")

    def test_number_dot_label(self):
        m = match_menu_choice(_OPTIONS, "1. Solicitar orçamento")
        self.assertEqual(m.handle_id, "opt_1")

    def test_number_paren_label(self):
        m = match_menu_choice(_OPTIONS, "1) Solicitar orçamento")
        self.assertEqual(m.handle_id, "opt_1")

    def test_number_dash_label(self):
        m = match_menu_choice(_OPTIONS, "1 - Solicitar orçamento")
        self.assertEqual(m.handle_id, "opt_1")

    def test_keycap_emoji_label(self):
        """Quick-reply do WhatsApp envia 1️⃣ Solicitar orçamento."""
        m = match_menu_choice(_OPTIONS, "1️⃣ Solicitar orçamento")
        self.assertIsNotNone(m)
        self.assertEqual(m.handle_id, "opt_1")

    def test_number_label_case_insensitive(self):
        m = match_menu_choice(_OPTIONS, "2 ver SERVIÇOS e preços")
        self.assertEqual(m.handle_id, "opt_2")

    # ---- Match por handle_id ----

    def test_handle_id_direct(self):
        m = match_menu_choice(_OPTIONS, "opt_3")
        self.assertEqual(m.handle_id, "opt_3")
        self.assertEqual(m.matched_by, "handle_id")

    # ---- Match por prefixo ----

    def test_prefix_match(self):
        m = match_menu_choice(_OPTIONS, "solic")
        self.assertEqual(m.handle_id, "opt_1")
        self.assertEqual(m.matched_by, "prefix")

    def test_too_short_prefix_returns_none(self):
        # "so" < 3 chars
        self.assertIsNone(match_menu_choice(_OPTIONS, "so"))

    # ---- Match por substring (mensagens conversacionais) ----

    def test_substring_in_sentence(self):
        m = match_menu_choice(
            _OPTIONS, "eu queria solicitar orçamento por favor",
        )
        self.assertEqual(m.handle_id, "opt_1")
        self.assertEqual(m.matched_by, "substring")

    # ---- Falsos positivos / segurança ----

    def test_number_with_spurious_text_short_rest(self):
        """'1 oi' tem 'oi' como rest curto → aceita pelo número."""
        m = match_menu_choice(_OPTIONS, "1 oi")
        self.assertIsNotNone(m)
        self.assertEqual(m.handle_id, "opt_1")

    def test_number_with_unrelated_long_text_returns_none(self):
        """'20 anos de experiência' não deveria selecionar opção 20."""
        # 20 está fora do range (4 opções), então retorna None de qq jeito
        self.assertIsNone(match_menu_choice(_OPTIONS, "20 anos"))

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(match_menu_choice(_OPTIONS, "blá blá blá"))

    def test_empty_text_returns_none(self):
        self.assertIsNone(match_menu_choice(_OPTIONS, ""))
        self.assertIsNone(match_menu_choice(_OPTIONS, "   "))
        self.assertIsNone(match_menu_choice(_OPTIONS, None))

    def test_empty_options_returns_none(self):
        self.assertIsNone(match_menu_choice([], "1"))
        self.assertIsNone(match_menu_choice(None, "1"))

    # ---- Casos específicos do screenshot do cliente ----

    def test_real_world_label_with_number_prefix(self):
        """Cliente cadastrou label como '1 Solicitar orçamento'
        (não típico, mas possível). Deve funcionar mesmo assim."""
        custom = [
            {"label": "1 Solicitar orçamento", "handle_id": "opt_a"},
            {"label": "2 Ver serviços", "handle_id": "opt_b"},
        ]
        # Label exato
        m = match_menu_choice(custom, "1 Solicitar orçamento")
        self.assertEqual(m.handle_id, "opt_a")
        # Só número
        m = match_menu_choice(custom, "1")
        self.assertEqual(m.handle_id, "opt_a")
