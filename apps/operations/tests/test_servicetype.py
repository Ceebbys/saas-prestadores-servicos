"""Testes do Serviço Pré-Fixado (ServiceType estendido)."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.crm.models import Pipeline, PipelineStage
from apps.operations.models import ServiceType
from apps.core.tests.helpers import (
    create_pipeline_for_empresa,
    create_test_empresa,
    create_test_user,
)


class ServiceTypeFieldsTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()

    def test_create_with_catalog_fields(self):
        st = ServiceType.objects.create(
            empresa=self.empresa,
            name="Topografia",
            category="Engenharia",
            default_price=Decimal("2500.00"),
            default_prazo_dias=15,
            tags="topo, georef",
        )
        self.assertEqual(st.default_price, Decimal("2500.00"))
        self.assertEqual(st.default_prazo_dias, 15)
        self.assertEqual(st.tag_list, ["topo", "georef"])

    def test_pipeline_stage_consistency_validation(self):
        create_pipeline_for_empresa(self.empresa)
        pipeline = Pipeline.objects.filter(empresa=self.empresa).first()
        # cria um pipeline secundário
        other = Pipeline.objects.create(
            empresa=self.empresa, name="Outro", is_default=False,
        )
        other_stage = PipelineStage.objects.create(
            pipeline=other, name="Etapa", order=0,
        )
        st = ServiceType(
            empresa=self.empresa, name="Inválido",
            default_pipeline=pipeline,
            default_stage=other_stage,
        )
        with self.assertRaises(ValidationError):
            st.clean()


class ServiceTypeViewTests(TestCase):
    def setUp(self):
        self.empresa = create_test_empresa()
        self.user = create_test_user("o@t.com", "O", self.empresa)
        self.client.force_login(self.user)

    def test_list_view_renders(self):
        ServiceType.objects.create(
            empresa=self.empresa, name="Levantamento",
            default_price=Decimal("1200.00"),
        )
        url = reverse("settings_app:service_type_list")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Levantamento", resp.content)
        self.assertIn(b"Servi\xc3\xa7os Pr\xc3\xa9-Fixados", resp.content)

    def test_other_tenant_isolation(self):
        outra = create_test_empresa(name="Outra", slug="outra")
        ServiceType.objects.create(
            empresa=outra, name="ServicoOutro",
            default_price=Decimal("500.00"),
        )
        url = reverse("settings_app:service_type_list")
        resp = self.client.get(url)
        self.assertNotIn(b"ServicoOutro", resp.content)
