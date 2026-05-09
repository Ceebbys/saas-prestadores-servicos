"""Testes do soft-delete de propostas."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.crm.models import Lead
from apps.proposals.models import Proposal
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


def _proposal(empresa, **kwargs):
    create_pipeline_for_empresa(empresa)
    lead = Lead.objects.create(empresa=empresa, name="Lead", email="l@e.com")
    kwargs.setdefault("title", "P")
    kwargs.setdefault("discount_percent", Decimal("0"))
    return Proposal.objects.create(empresa=empresa, lead=lead, **kwargs)


class SoftDeleteModelTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()

    def test_default_manager_hides_soft_deleted(self):
        p = _proposal(self.empresa)
        p.delete()  # soft-delete

        self.assertFalse(Proposal.objects.filter(pk=p.pk).exists())
        self.assertTrue(Proposal.all_objects.filter(pk=p.pk).exists())

    def test_delete_sets_deleted_at(self):
        p = _proposal(self.empresa)
        before = timezone.now()
        p.delete()
        p.refresh_from_db()
        self.assertIsNotNone(p.deleted_at)
        self.assertGreaterEqual(p.deleted_at, before)

    def test_restore_clears_deleted_at(self):
        p = _proposal(self.empresa)
        p.delete()
        p.refresh_from_db()
        p.restore()
        p.refresh_from_db()
        self.assertIsNone(p.deleted_at)
        # Reaparece no manager default
        self.assertTrue(Proposal.objects.filter(pk=p.pk).exists())

    def test_hard_delete_actually_removes(self):
        p = _proposal(self.empresa)
        pk = p.pk
        p.hard_delete()
        self.assertFalse(Proposal.all_objects.filter(pk=pk).exists())

    def test_queryset_alive_and_deleted(self):
        alive = _proposal(self.empresa, title="vivo")
        dead = _proposal(self.empresa, title="morto")
        dead.delete()
        all_qs = Proposal.all_objects.filter(empresa=self.empresa)
        self.assertEqual(all_qs.alive().count(), 1)
        self.assertEqual(all_qs.deleted().count(), 1)
        self.assertEqual(all_qs.alive().first().pk, alive.pk)


class TrashViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("t@t.com", "T", self.empresa)
        self.client.force_login(self.user)

    def test_trash_lists_only_soft_deleted(self):
        alive = _proposal(self.empresa, title="vivo")
        dead = _proposal(self.empresa, title="morto")
        dead.delete()
        resp = self.client.get(reverse("proposals:trash"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"morto", resp.content)
        self.assertNotIn(b"vivo", resp.content)

    def test_restore_endpoint(self):
        p = _proposal(self.empresa)
        p.delete()
        url = reverse("proposals:restore", args=[p.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        p.refresh_from_db()
        self.assertIsNone(p.deleted_at)

    def test_hard_delete_endpoint_only_works_on_trashed(self):
        p = _proposal(self.empresa)
        # Tentando hard-delete de proposta não-soft-deleted → 404
        url = reverse("proposals:hard_delete", args=[p.pk])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Proposal.all_objects.filter(pk=p.pk).exists())

        # Após soft-delete, hard-delete funciona
        p.delete()
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Proposal.all_objects.filter(pk=p.pk).exists())

    def test_other_tenant_cannot_see_or_restore(self):
        outra = create_test_empresa(name="X", slug="x")
        p = _proposal(outra)
        p.delete()
        # Lista de lixeira não mostra
        resp = self.client.get(reverse("proposals:trash"))
        self.assertNotContains(resp, p.number)
        # Tentar restaurar → 404
        resp = self.client.post(reverse("proposals:restore", args=[p.pk]))
        self.assertEqual(resp.status_code, 404)


class PurgeCommandTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()

    def test_purge_old_soft_deleted(self):
        from django.core.management import call_command

        old = _proposal(self.empresa)
        old.delete()
        # Forçar deleted_at para 70 dias atrás
        Proposal.all_objects.filter(pk=old.pk).update(
            deleted_at=timezone.now() - timedelta(days=70),
        )

        recent = _proposal(self.empresa)
        recent.delete()  # excluído agora — fica

        call_command("purge_deleted_proposals", "--days=60")

        self.assertFalse(Proposal.all_objects.filter(pk=old.pk).exists())
        self.assertTrue(Proposal.all_objects.filter(pk=recent.pk).exists())

    def test_dry_run_does_not_delete(self):
        from django.core.management import call_command

        p = _proposal(self.empresa)
        p.delete()
        Proposal.all_objects.filter(pk=p.pk).update(
            deleted_at=timezone.now() - timedelta(days=120),
        )
        call_command("purge_deleted_proposals", "--days=60", "--dry-run")
        self.assertTrue(Proposal.all_objects.filter(pk=p.pk).exists())
