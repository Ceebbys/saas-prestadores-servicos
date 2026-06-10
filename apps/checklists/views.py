"""RV08 (2.1/2.2) — Endpoints HTMX dos checklists múltiplos.

Cada mutação devolve o bloco completo de checklists do dono re-renderizado
(swap ``outerHTML`` no contêiner) — mantém o estado consistente sem JS extra.
"""
from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views import View

from apps.core.mixins import EmpresaMixin

from .models import Checklist, ChecklistItem
from .services import (
    owner_type_for,
    render_checklists_block,
    resolve_owner,
)


def _block(request, owner, owner_type):
    # RV08 — defensivo: se o dono (GenericFK) sumiu (órfão raro vindo de
    # import/dados crus), não renderiza nada em vez de estourar AttributeError.
    if owner is None:
        return HttpResponse("")
    return HttpResponse(render_checklists_block(request, owner, owner_type))


class ChecklistAddView(EmpresaMixin, View):
    http_method_names = ["post"]

    def post(self, request, owner_type, owner_id):
        owner = resolve_owner(owner_type, owner_id, request.empresa)
        name = (request.POST.get("name") or "").strip() or "Checklist"
        from django.contrib.contenttypes.models import ContentType
        from django.db.models import Max

        ct = ContentType.objects.get_for_model(owner.__class__)
        next_order = (
            Checklist.objects.filter(
                empresa=request.empresa, content_type=ct, object_id=owner.pk,
            ).aggregate(m=Max("order"))["m"] or 0
        ) + 1
        Checklist.objects.create(
            empresa=request.empresa, content_type=ct, object_id=owner.pk,
            name=name[:120], order=next_order,
        )
        return _block(request, owner, owner_type)


class ChecklistRenameView(EmpresaMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        checklist = get_object_or_404(Checklist, pk=pk, empresa=request.empresa)
        name = (request.POST.get("name") or "").strip()
        if name:
            checklist.name = name[:120]
            checklist.save(update_fields=["name", "updated_at"])
        return _block(request, checklist.owner, owner_type_for(checklist.owner))


class ChecklistDeleteView(EmpresaMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        checklist = get_object_or_404(Checklist, pk=pk, empresa=request.empresa)
        owner, owner_type = checklist.owner, owner_type_for(checklist.owner)
        checklist.delete()
        return _block(request, owner, owner_type)


class ChecklistItemAddView(EmpresaMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        checklist = get_object_or_404(Checklist, pk=pk, empresa=request.empresa)
        desc = (request.POST.get("description") or "").strip()
        if desc:
            from django.db.models import Max

            next_order = (
                checklist.items.aggregate(m=Max("order"))["m"] or 0
            ) + 1
            ChecklistItem.objects.create(
                checklist=checklist, description=desc[:500], order=next_order,
            )
        return _block(request, checklist.owner, owner_type_for(checklist.owner))


class ChecklistItemToggleView(EmpresaMixin, View):
    http_method_names = ["post"]

    def post(self, request, item_pk):
        item = get_object_or_404(
            ChecklistItem, pk=item_pk, checklist__empresa=request.empresa,
        )
        item.toggle()
        owner = item.checklist.owner
        return _block(request, owner, owner_type_for(owner))


class ChecklistItemEditView(EmpresaMixin, View):
    http_method_names = ["post"]

    def post(self, request, item_pk):
        item = get_object_or_404(
            ChecklistItem, pk=item_pk, checklist__empresa=request.empresa,
        )
        desc = (request.POST.get("description") or "").strip()
        if desc:
            item.description = desc[:500]
            item.save(update_fields=["description", "updated_at"])
        owner = item.checklist.owner
        return _block(request, owner, owner_type_for(owner))


class ChecklistItemDeleteView(EmpresaMixin, View):
    http_method_names = ["post"]

    def post(self, request, item_pk):
        item = get_object_or_404(
            ChecklistItem, pk=item_pk, checklist__empresa=request.empresa,
        )
        owner = item.checklist.owner
        item.delete()
        return _block(request, owner, owner_type_for(owner))
