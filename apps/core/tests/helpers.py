"""Funções auxiliares compartilhadas por todos os módulos de teste."""

import sys

from apps.accounts.models import Empresa, Membership, User


def patch_django_python314():
    """Corrige bugs de Django 5.1 + Python 3.14.

    1. BaseContext.__copy__ falha porque super().__copy__() não funciona
       em Python 3.14 quando __slots__ está envolvido.
    2. Context.__init__ não seta 'template' em Python 3.14 devido a
       mudanças em __slots__ handling.
    """
    if sys.version_info < (3, 14):
        return

    from django.template.context import BaseContext, Context, RequestContext

    # Fix 1: __copy__ — copy all instance attributes, not just dicts
    def _safe_copy(self):
        duplicate = self.__class__.__new__(self.__class__)
        duplicate.__dict__.update(self.__dict__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    BaseContext.__copy__ = _safe_copy

    # Fix 2: Ensure 'template' attribute exists on Context subclasses
    _original_context_init = Context.__init__

    def _patched_context_init(self, *args, **kwargs):
        _original_context_init(self, *args, **kwargs)
        if not hasattr(self, "template"):
            self.template = None
        if not hasattr(self, "template_name"):
            self.template_name = None
        if not hasattr(self, "render_context"):
            from django.template.context import RenderContext
            self.render_context = RenderContext()

    Context.__init__ = _patched_context_init

    _original_rc_init = RequestContext.__init__

    def _patched_rc_init(self, *args, **kwargs):
        _original_rc_init(self, *args, **kwargs)
        if not hasattr(self, "template"):
            self.template = None
        if not hasattr(self, "template_name"):
            self.template_name = None
        if not hasattr(self, "render_context"):
            from django.template.context import RenderContext
            self.render_context = RenderContext()

    RequestContext.__init__ = _patched_rc_init


patch_django_python314()


def create_test_empresa(name="Empresa A", slug="empresa-a", segment="topografia"):
    """Cria uma Empresa de teste."""
    return Empresa.objects.create(name=name, slug=slug, segment=segment)


def create_test_user(email, full_name, empresa, password="TestPass123!"):
    """Cria um User com Membership OWNER e active_empresa setado."""
    user = User.objects.create_user(
        email=email, full_name=full_name, password=password,
    )
    Membership.objects.create(
        user=user, empresa=empresa, role=Membership.Role.OWNER, is_active=True,
    )
    user.active_empresa = empresa
    user.save(update_fields=["active_empresa"])
    return user


def create_two_tenants():
    """Cria 2 empresas isoladas com 1 user cada.

    Returns:
        dict com empresa_a, user_a, empresa_b, user_b
    """
    empresa_a = create_test_empresa("Empresa A", "empresa-a", "topografia")
    user_a = create_test_user("usera@test.com", "User A", empresa_a)

    empresa_b = create_test_empresa("Empresa B", "empresa-b", "engenharia")
    user_b = create_test_user("userb@test.com", "User B", empresa_b)

    return {
        "empresa_a": empresa_a,
        "user_a": user_a,
        "empresa_b": empresa_b,
        "user_b": user_b,
    }


def create_pipeline_for_empresa(empresa):
    """Cria Pipeline com 3 stages (Novo, Negociando, Fechado).

    Returns:
        tuple (pipeline, stage_novo, stage_negociando, stage_fechado)
    """
    from apps.crm.models import Pipeline, PipelineStage

    pipeline = Pipeline.objects.create(
        empresa=empresa, name="Pipeline Principal", is_default=True,
    )
    stage_novo = PipelineStage.objects.create(
        pipeline=pipeline, name="Novo", order=0, color="#6366F1",
    )
    stage_negociando = PipelineStage.objects.create(
        pipeline=pipeline, name="Negociando", order=1, color="#F59E0B",
    )
    stage_fechado = PipelineStage.objects.create(
        pipeline=pipeline, name="Fechado", order=2, color="#10B981", is_won=True,
    )
    return pipeline, stage_novo, stage_negociando, stage_fechado
