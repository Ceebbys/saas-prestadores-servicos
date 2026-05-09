"""Testes do SMTP por tenant (EmpresaEmailConfig + Fernet + resolução)."""
from cryptography.fernet import Fernet
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings

from apps.accounts.models import EmpresaEmailConfig
from apps.core.encryption import decrypt, encrypt
from apps.core.tests.helpers import create_test_empresa, create_test_user

# Chave Fernet fixa só para o ambiente de testes — não usada em produção.
TEST_FERNET_KEY = Fernet.generate_key().decode()


@override_settings(FERNET_KEY=TEST_FERNET_KEY)
class FernetEncryptionTests(TestCase):
    def test_encrypt_decrypt_round_trip(self):
        plaintext = "minha-senha-app-gmail-2026"
        cipher = encrypt(plaintext)
        self.assertNotEqual(cipher, plaintext)
        self.assertEqual(decrypt(cipher), plaintext)

    def test_empty_returns_empty(self):
        self.assertEqual(encrypt(""), "")
        self.assertEqual(decrypt(""), "")

    def test_corrupt_ciphertext_returns_empty(self):
        self.assertEqual(decrypt("not-a-valid-token"), "")


@override_settings(FERNET_KEY=TEST_FERNET_KEY)
class EmpresaEmailConfigModelTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()

    def test_set_password_encrypts_and_get_password_decrypts(self):
        cfg = EmpresaEmailConfig.objects.create(
            empresa=self.empresa,
            host="smtp.gmail.com", port=587,
            username="me@example.com",
            from_email="me@example.com",
        )
        cfg.set_password("super-secret")
        cfg.save()

        # Re-fetch from DB
        cfg2 = EmpresaEmailConfig.objects.get(pk=cfg.pk)
        self.assertNotIn("super-secret", cfg2.password_encrypted)
        self.assertEqual(cfg2.get_password(), "super-secret")

    def test_get_from_address_with_name(self):
        cfg = EmpresaEmailConfig.objects.create(
            empresa=self.empresa,
            host="smtp.gmail.com", port=587,
            username="me@example.com",
            from_email="me@example.com",
            from_name="Minha Empresa",
        )
        self.assertEqual(cfg.get_from_address(), "Minha Empresa <me@example.com>")

    def test_get_from_address_falls_back_to_empresa_name(self):
        cfg = EmpresaEmailConfig.objects.create(
            empresa=self.empresa,
            host="smtp.gmail.com", port=587,
            username="me@example.com",
            from_email="me@example.com",
            from_name="",
        )
        self.assertIn(self.empresa.name, cfg.get_from_address())


@override_settings(FERNET_KEY=TEST_FERNET_KEY)
class EmailServiceResolutionTests(TestCase):
    """`send_proposal_email` resolve SMTP do tenant primeiro, fallback global."""

    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("e@t.com", "E", self.empresa)

    @override_settings(DEFAULT_FROM_EMAIL="global@servicopro.app")
    def test_no_config_uses_global_from(self):
        from apps.proposals.services.email import _resolve_smtp_for

        connection, from_email = _resolve_smtp_for(self.empresa)
        self.assertIsNone(connection)
        self.assertEqual(from_email, "global@servicopro.app")

    def test_active_config_returns_tenant_connection(self):
        cfg = EmpresaEmailConfig.objects.create(
            empresa=self.empresa,
            host="smtp.gmail.com", port=587,
            username="me@example.com",
            from_email="me@example.com",
            from_name="Minha Empresa",
            is_active=True,
        )
        cfg.set_password("pwd123")
        cfg.save()

        from apps.proposals.services.email import _resolve_smtp_for

        connection, from_email = _resolve_smtp_for(self.empresa)
        self.assertIsNotNone(connection)
        self.assertIn("Minha Empresa", from_email)
        self.assertEqual(connection.host, "smtp.gmail.com")
        self.assertEqual(connection.username, "me@example.com")
        self.assertEqual(connection.password, "pwd123")

    @override_settings(DEFAULT_FROM_EMAIL="global@servicopro.app")
    def test_inactive_config_falls_back_to_global(self):
        cfg = EmpresaEmailConfig.objects.create(
            empresa=self.empresa,
            host="smtp.gmail.com", port=587,
            username="me@example.com",
            from_email="me@example.com",
            is_active=False,
        )
        cfg.set_password("pwd")
        cfg.save()

        from apps.proposals.services.email import _resolve_smtp_for

        connection, from_email = _resolve_smtp_for(self.empresa)
        self.assertIsNone(connection)
        self.assertEqual(from_email, "global@servicopro.app")
