"""Helpers do app de checklists: resolução do "dono" (genérico) + render HTMX."""
from __future__ import annotations

from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string

from .models import Checklist

# Tipos de dono permitidos (slug → "app.Model"). Restrito de propósito para não
# permitir anexar checklist a qualquer modelo via URL adivinhada.
OWNER_TYPES = {
    "opportunity": "crm.Opportunity",
    "work_order": "operations.WorkOrder",
}
MODEL_TO_OWNER_TYPE = {
    "Opportunity": "opportunity",
    "WorkOrder": "work_order",
}


def resolve_owner(owner_type: str, owner_id, empresa):
    """Retorna a instância do dono garantindo isolamento por empresa."""
    dotted = OWNER_TYPES.get(owner_type)
    if dotted is None:
        from django.http import Http404

        raise Http404("Tipo de dono de checklist inválido.")
    model = django_apps.get_model(dotted)
    return get_object_or_404(model, pk=owner_id, empresa=empresa)


def owner_type_for(instance) -> str:
    return MODEL_TO_OWNER_TYPE.get(instance.__class__.__name__, "")


def checklists_for(owner):
    return (
        Checklist.objects.filter(
            empresa=owner.empresa,
            content_type=ContentType.objects.get_for_model(owner.__class__),
            object_id=owner.pk,
        )
        .prefetch_related("items")
    )


def render_checklists_block(request, owner, owner_type: str) -> str:
    """Renderiza o bloco completo de checklists do dono (para swap via HTMX)."""
    return render_to_string(
        "checklists/_checklists.html",
        {
            "checklists": checklists_for(owner),
            "owner_type": owner_type,
            "owner_id": owner.pk,
        },
        request=request,
    )
