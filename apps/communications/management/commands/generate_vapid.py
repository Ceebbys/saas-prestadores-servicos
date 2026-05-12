"""Gera par de chaves VAPID para Web Push.

Uso:
    python manage.py generate_vapid

Cola as duas chaves em .env (VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY) e
reinicia o servidor.
"""
from __future__ import annotations

import base64

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Gera par de chaves VAPID (ECDSA P-256) para Web Push."

    def handle(self, *args, **options):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec
        except ImportError:
            self.stderr.write(self.style.ERROR(
                "cryptography não instalado. pip install cryptography."
            ))
            return

        # Gera P-256
        private_key = ec.generate_private_key(ec.SECP256R1())

        # Private em base64url (PKCS8 raw → 32 bytes)
        private_value = private_key.private_numbers().private_value
        private_bytes = private_value.to_bytes(32, byteorder="big")
        private_b64 = base64.urlsafe_b64encode(private_bytes).rstrip(b"=").decode("ascii")

        # Public em base64url (uncompressed point: 0x04 + X + Y)
        public_numbers = private_key.public_key().public_numbers()
        x_bytes = public_numbers.x.to_bytes(32, byteorder="big")
        y_bytes = public_numbers.y.to_bytes(32, byteorder="big")
        point = b"\x04" + x_bytes + y_bytes
        public_b64 = base64.urlsafe_b64encode(point).rstrip(b"=").decode("ascii")

        self.stdout.write(self.style.SUCCESS("Chaves VAPID geradas com sucesso!"))
        self.stdout.write("")
        self.stdout.write("Adicione ao seu .env:")
        self.stdout.write("")
        self.stdout.write(f"VAPID_PUBLIC_KEY={public_b64}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={private_b64}")
        self.stdout.write("VAPID_CONTACT_EMAIL=admin@servicopro.app")
        self.stdout.write("")
        self.stdout.write(
            "Após salvar, reinicie o servidor. Frontend obtém a chave "
            "pública via GET /inbox/notifications/vapid-public-key/."
        )
