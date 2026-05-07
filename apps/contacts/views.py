from django.contrib import messages
from django.db.models import Count
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from apps.core.mixins import EmpresaMixin, HtmxResponseMixin

from .forms import ContatoForm
from .models import Contato
from .services import search_contatos


class ContactListView(EmpresaMixin, HtmxResponseMixin, ListView):
    model = Contato
    template_name = "contacts/contact_list.html"
    partial_template_name = "contacts/partials/_contact_table.html"
    context_object_name = "contacts"
    paginate_by = 20

    def get_queryset(self):
        from django.db.models import Q

        from apps.core.validators import normalize_document

        qs = Contato.objects.filter(empresa=self.request.empresa)
        q = self.request.GET.get("q", "").strip()
        active = self.request.GET.get("active", "").strip()
        if q:
            digits = normalize_document(q)
            filters = (
                Q(name__icontains=q)
                | Q(phone__icontains=q)
                | Q(whatsapp__icontains=q)
                | Q(email__icontains=q)
                | Q(company__icontains=q)
            )
            if digits:
                filters |= Q(cpf_cnpj_normalized__startswith=digits)
            qs = qs.filter(filters)
        if active == "1":
            qs = qs.filter(is_active=True)
        elif active == "0":
            qs = qs.filter(is_active=False)
        return qs.annotate(leads_count=Count("leads")).order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_q"] = self.request.GET.get("q", "")
        context["current_active"] = self.request.GET.get("active", "")
        return context


class ContactDetailView(EmpresaMixin, DetailView):
    model = Contato
    template_name = "contacts/contact_detail.html"
    context_object_name = "contato"

    def get_queryset(self):
        return Contato.objects.filter(empresa=self.request.empresa)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["leads"] = self.object.leads.select_related("pipeline_stage")[:50]
        return context


class ContactCreateView(EmpresaMixin, HtmxResponseMixin, CreateView):
    model = Contato
    form_class = ContatoForm
    template_name = "contacts/contact_form.html"
    partial_template_name = "contacts/partials/_contact_form.html"
    success_url = reverse_lazy("contacts:list")

    def form_valid(self, form):
        form.validate_unique_for_empresa(self.request.empresa)
        if form.errors:
            return self.form_invalid(form)
        contato = form.save(commit=False)
        contato.empresa = self.request.empresa
        contato.save()
        messages.success(self.request, "Contato criado com sucesso.")
        return redirect("contacts:detail", pk=contato.pk)


class ContactUpdateView(EmpresaMixin, HtmxResponseMixin, UpdateView):
    model = Contato
    form_class = ContatoForm
    template_name = "contacts/contact_form.html"
    partial_template_name = "contacts/partials/_contact_form.html"

    def get_queryset(self):
        return Contato.objects.filter(empresa=self.request.empresa)

    def form_valid(self, form):
        form.validate_unique_for_empresa(self.request.empresa)
        if form.errors:
            return self.form_invalid(form)
        contato = form.save()
        messages.success(self.request, "Contato atualizado com sucesso.")
        return redirect("contacts:detail", pk=contato.pk)


class ContactDeleteView(EmpresaMixin, DeleteView):
    model = Contato
    success_url = reverse_lazy("contacts:list")
    http_method_names = ["post"]

    def get_queryset(self):
        return Contato.objects.filter(empresa=self.request.empresa)

    def post(self, request, *args, **kwargs):
        try:
            response = self.delete(request, *args, **kwargs)
            messages.success(request, "Contato excluído com sucesso.")
            return response
        except Exception:
            messages.error(
                request,
                "Não foi possível excluir este contato porque ele "
                "está vinculado a um ou mais leads.",
            )
            return redirect("contacts:detail", pk=self.kwargs["pk"])


class ContactAutocompleteView(EmpresaMixin, ListView):
    """HTMX endpoint: retorna uma partial com até 10 contatos para o builder."""
    template_name = "contacts/partials/_autocomplete_results.html"
    context_object_name = "contacts"

    def get_queryset(self):
        q = self.request.GET.get("q", "").strip()
        return search_contatos(self.request.empresa, q, limit=10)
