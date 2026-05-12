"""Views CRUD para MessageTemplate + endpoints API para composer (Fase 5)."""
from __future__ import annotations

import json
import logging

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from apps.communications.models import Conversation, MessageTemplate
from apps.core.mixins import EmpresaMixin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------


from django import forms

from apps.core.forms import TailwindFormMixin


class MessageTemplateForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = MessageTemplate
        fields = ["name", "shortcut", "category", "channel", "content", "is_active"]
        widgets = {
            "content": forms.Textarea(attrs={
                "rows": 6,
                "placeholder": "Olá {{ lead.name }}! Recebemos seu contato.",
            }),
            "shortcut": forms.TextInput(attrs={
                "placeholder": "ola, preco, retorno",
                "autocomplete": "off",
            }),
        }

    def clean_shortcut(self):
        s = (self.cleaned_data.get("shortcut") or "").strip().lower()
        if s:
            invalid = [c for c in s if not (c.isalnum() or c in "_-")]
            if invalid:
                raise forms.ValidationError(
                    "Atalho aceita apenas letras, números, '_' e '-'.",
                )
        return s


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TemplateListView(EmpresaMixin, ListView):
    model = MessageTemplate
    template_name = "communications/templates/list.html"
    context_object_name = "templates"
    paginate_by = 50

    def get_queryset(self):
        qs = MessageTemplate.objects.filter(
            empresa=self.request.empresa,
        ).order_by("category", "name")
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        cat = (self.request.GET.get("category") or "").strip()
        if cat and cat != "all":
            qs = qs.filter(category=cat)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["search_q"] = self.request.GET.get("q", "")
        ctx["category_filter"] = self.request.GET.get("category", "all")
        ctx["category_choices"] = MessageTemplate.Category.choices
        return ctx


class TemplateCreateView(EmpresaMixin, CreateView):
    model = MessageTemplate
    form_class = MessageTemplateForm
    template_name = "communications/templates/form.html"

    def form_valid(self, form):
        form.instance.empresa = self.request.empresa
        form.instance.created_by = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        from django.urls import reverse
        return reverse("communications:template_list")


class TemplateUpdateView(EmpresaMixin, UpdateView):
    model = MessageTemplate
    form_class = MessageTemplateForm
    template_name = "communications/templates/form.html"

    def get_queryset(self):
        return MessageTemplate.objects.filter(empresa=self.request.empresa)

    def get_success_url(self):
        from django.urls import reverse
        return reverse("communications:template_list")


class TemplateDeleteView(EmpresaMixin, DeleteView):
    model = MessageTemplate
    template_name = "communications/templates/confirm_delete.html"

    def get_queryset(self):
        return MessageTemplate.objects.filter(empresa=self.request.empresa)

    def get_success_url(self):
        from django.urls import reverse
        return reverse("communications:template_list")


# ---------------------------------------------------------------------------
# API para composer
# ---------------------------------------------------------------------------


class TemplateSearchView(EmpresaMixin, View):
    """GET ?q=... — retorna até 10 templates do tenant matching name/shortcut.

    Usado pelo dropdown que aparece ao digitar '/' no composer.
    Retorna JSON com lista compacta.
    """

    http_method_names = ["get"]
    LIMIT = 15

    def get(self, request):
        q = (request.GET.get("q") or "").strip().lower().lstrip("/")
        channel = (request.GET.get("channel") or "").strip()
        qs = MessageTemplate.objects.filter(
            empresa=request.empresa, is_active=True,
        )
        if channel:
            from django.db.models import Q
            qs = qs.filter(
                Q(channel=channel) | Q(channel=MessageTemplate.Channel.ANY)
            )
        if q:
            from django.db.models import Q
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(shortcut__startswith=q)
                | Q(content__icontains=q)
            )
        qs = qs.order_by("-usage_count", "name")[: self.LIMIT]
        data = [
            {
                "id": t.pk,
                "name": t.name,
                "shortcut": t.shortcut,
                "category": t.category,
                "category_display": t.get_category_display(),
                "channel": t.channel,
                "preview": (t.content or "")[:160],
            }
            for t in qs
        ]
        return JsonResponse({"templates": data})


class TemplateRenderView(EmpresaMixin, View):
    """GET — renderiza template no contexto da conversa para preview/inserção.

    Retorna `{rendered: "...", template_id: N}`.
    """

    http_method_names = ["get"]

    def get(self, request, pk: int, conv_pk: int):
        from apps.communications.templates_service import render_and_track

        tpl = get_object_or_404(
            MessageTemplate, pk=pk, empresa=request.empresa, is_active=True,
        )
        conv = get_object_or_404(
            Conversation, pk=conv_pk, empresa=request.empresa,
        )
        rendered = render_and_track(
            tpl, conversation=conv, user=request.user, empresa=request.empresa,
        )
        return JsonResponse({"rendered": rendered, "template_id": tpl.pk})
