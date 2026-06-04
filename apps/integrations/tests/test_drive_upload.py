"""RV07 (Epic 7) — Upload de arquivo da OS para o Google Drive (provider mockado)."""
from datetime import timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.tests.helpers import create_test_empresa, create_test_user
from apps.integrations import services
from apps.integrations.models import IntegrationConnection
from apps.integrations.providers.base import ProviderResult
from apps.integrations.providers.google import GoogleStorageProvider
from apps.operations.models import WorkOrder


def _drive_conn(empresa):
    conn = IntegrationConnection.objects.create(
        empresa=empresa, provider=IntegrationConnection.Provider.GOOGLE,
        status=IntegrationConnection.Status.CONNECTED, scopes=["calendar", "drive"],
    )
    conn.set_access_token("at")
    conn.set_refresh_token("rt")
    conn.expires_at = timezone.now() + timedelta(hours=1)
    conn.save()
    return conn


class UploadServiceTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="drive-svc")

    def test_no_connection_is_noop(self):
        wo = WorkOrder.objects.create(empresa=self.empresa, title="OS")
        res = services.upload_file_to_workorder_drive(
            wo, filename="a.pdf", content=b"x",
        )
        self.assertEqual(res.get("status"), "not_configured")

    def test_creates_folder_uploads_and_appends_link(self):
        _drive_conn(self.empresa)
        wo = WorkOrder.objects.create(empresa=self.empresa, title="OS Drive")
        with patch.object(
            GoogleStorageProvider, "create_folder",
            return_value=ProviderResult(status="ok", file_id="fold1"),
        ) as mock_folder, patch.object(
            GoogleStorageProvider, "upload_file",
            return_value=ProviderResult(status="ok", file_id="file1", web_link="http://f"),
        ) as mock_up, patch.object(
            GoogleStorageProvider, "share_link",
            return_value=ProviderResult(status="ok", web_link="http://share"),
        ):
            res = services.upload_file_to_workorder_drive(
                wo, filename="proposta.pdf", content=b"PDF", mime="application/pdf",
            )
        self.assertEqual(res["status"], "ok")
        mock_folder.assert_called_once()
        mock_up.assert_called_once()
        wo.refresh_from_db()
        self.assertEqual(wo.google_drive_folder_id, "fold1")
        self.assertEqual(len(wo.cloud_storage_links), 1)
        self.assertEqual(wo.cloud_storage_links[0]["label"], "proposta.pdf")
        self.assertEqual(wo.cloud_storage_links[0]["url"], "http://share")

    def test_reuses_existing_folder(self):
        _drive_conn(self.empresa)
        wo = WorkOrder.objects.create(
            empresa=self.empresa, title="OS", google_drive_folder_id="existing",
        )
        with patch.object(GoogleStorageProvider, "create_folder") as mock_folder, \
            patch.object(
                GoogleStorageProvider, "upload_file",
                return_value=ProviderResult(status="ok", file_id="file2", web_link="http://f"),
            ), patch.object(
                GoogleStorageProvider, "share_link",
                return_value=ProviderResult(status="ok", web_link="http://s"),
            ):
            services.upload_file_to_workorder_drive(wo, filename="b.png", content=b"img")
        mock_folder.assert_not_called()


class UploadViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa(slug="drive-view")
        self.user = create_test_user("d@t.com", "D", self.empresa)
        self.client.force_login(self.user)
        self.wo = WorkOrder.objects.create(empresa=self.empresa, title="OS V")

    def test_upload_posts_file_and_redirects(self):
        f = SimpleUploadedFile("doc.pdf", b"PDFDATA", content_type="application/pdf")
        with patch(
            "apps.integrations.services.upload_file_to_workorder_drive",
            return_value=ProviderResult(status="ok", web_link="http://x", label="doc.pdf"),
        ) as mock_svc:
            resp = self.client.post(
                reverse("operations:work_order_drive_upload", args=[self.wo.pk]),
                {"file": f},
            )
        self.assertEqual(resp.status_code, 302)
        mock_svc.assert_called_once()

    def test_upload_without_file_errors_gracefully(self):
        resp = self.client.post(
            reverse("operations:work_order_drive_upload", args=[self.wo.pk]), {},
        )
        self.assertEqual(resp.status_code, 302)  # redireciona com mensagem de erro

    def test_detail_shows_upload_when_drive_connected(self):
        _drive_conn(self.empresa)
        resp = self.client.get(
            reverse("operations:work_order_detail", args=[self.wo.pk]),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Enviar para o Google Drive")

    def test_detail_hides_upload_without_drive(self):
        resp = self.client.get(
            reverse("operations:work_order_detail", args=[self.wo.pk]),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Enviar para o Google Drive")
