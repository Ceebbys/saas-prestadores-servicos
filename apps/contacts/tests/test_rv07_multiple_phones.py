"""RV07 — Item 4.2: múltiplos telefones por contato.

Mantém os campos legados phone/whatsapp sincronizados a partir da lista de
telefones, para compatibilidade com busca/autocomplete/whatsapp_or_phone.
"""
import json

from django.test import TestCase

from apps.contacts.forms import ContatoForm
from apps.contacts.models import Contato, ContatoTelefone
from apps.core.tests.helpers import create_test_empresa


class MultiplePhonesFormTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="rv07-phones")

    def _form(self, telefones, instance=None, **extra):
        data = {
            "name": "Cliente",
            "is_active": "on",
            "telefones_json": json.dumps(telefones),
        }
        data.update(extra)
        return ContatoForm(data=data, instance=instance)

    def _save(self, form):
        form.instance.empresa = self.empresa
        return form.save()

    def test_creates_multiple_phones_and_syncs_primary(self):
        tels = [
            {"tipo": "celular", "numero": "11999990000", "is_principal": True},
            {"tipo": "whatsapp", "numero": "11888887777", "is_principal": False},
            {"tipo": "comercial", "numero": "1133334444", "is_principal": False},
        ]
        form = self._form(tels)
        self.assertTrue(form.is_valid(), form.errors)
        contato = self._save(form)

        self.assertEqual(contato.telefones.count(), 3)
        # phone = principal (celular); whatsapp = primeiro do tipo whatsapp
        self.assertEqual(contato.phone, "11999990000")
        self.assertEqual(contato.whatsapp, "11888887777")
        self.assertEqual(contato.whatsapp_or_phone, "11888887777")

    def test_edit_reconciles_add_update_delete(self):
        contato = Contato.objects.create(empresa=self.empresa, name="C")
        t1 = ContatoTelefone.objects.create(
            contato=contato, tipo="celular", numero="111", is_principal=True, order=0,
        )
        t2 = ContatoTelefone.objects.create(
            contato=contato, tipo="fixo", numero="222", order=1,
        )
        tels = [
            {"id": t1.id, "tipo": "celular", "numero": "111-edit", "is_principal": True},
            {"tipo": "whatsapp", "numero": "333", "is_principal": False},  # novo
        ]
        form = self._form(tels, instance=contato)
        self.assertTrue(form.is_valid(), form.errors)
        self._save(form)

        numeros = set(contato.telefones.values_list("numero", flat=True))
        self.assertEqual(numeros, {"111-edit", "333"})
        self.assertFalse(ContatoTelefone.objects.filter(id=t2.id).exists())
        self.assertTrue(ContatoTelefone.objects.filter(id=t1.id).exists())

    def test_no_principal_defaults_to_first(self):
        tels = [
            {"tipo": "celular", "numero": "111", "is_principal": False},
            {"tipo": "fixo", "numero": "222", "is_principal": False},
        ]
        form = self._form(tels)
        self.assertTrue(form.is_valid(), form.errors)
        contato = self._save(form)
        principais = contato.telefones.filter(is_principal=True)
        self.assertEqual(principais.count(), 1)
        self.assertEqual(principais.first().numero, "111")

    def test_only_one_principal_kept(self):
        tels = [
            {"tipo": "celular", "numero": "111", "is_principal": True},
            {"tipo": "fixo", "numero": "222", "is_principal": True},  # 2º principal
        ]
        form = self._form(tels)
        self.assertTrue(form.is_valid(), form.errors)
        contato = self._save(form)
        self.assertEqual(contato.telefones.filter(is_principal=True).count(), 1)

    def test_legacy_phone_seeds_editor_initial(self):
        contato = Contato.objects.create(
            empresa=self.empresa, name="Antigo",
            phone="11999990000", whatsapp="11888887777",
        )
        form = ContatoForm(instance=contato)
        seeded = json.loads(form.initial["telefones_json"])
        numeros = {t["numero"] for t in seeded}
        self.assertIn("11999990000", numeros)
        self.assertIn("11888887777", numeros)

    def test_empty_numero_lines_ignored(self):
        tels = [
            {"tipo": "celular", "numero": "111", "is_principal": True},
            {"tipo": "celular", "numero": "   ", "is_principal": False},
        ]
        form = self._form(tels)
        self.assertTrue(form.is_valid(), form.errors)
        contato = self._save(form)
        self.assertEqual(contato.telefones.count(), 1)
