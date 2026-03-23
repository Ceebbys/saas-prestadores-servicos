from django.contrib.auth.mixins import LoginRequiredMixin


class EmpresaMixin(LoginRequiredMixin):
    """
    View mixin that:
    - Requires authentication
    - Filters querysets by the current empresa
    - Sets empresa on form save
    - Adds empresa to template context
    """

    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(qs.model, "empresa"):
            return qs.filter(empresa=self.request.empresa)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["empresa"] = self.request.empresa
        return context

    def form_valid(self, form):
        if hasattr(form.instance, "empresa_id") and not form.instance.empresa_id:
            form.instance.empresa = self.request.empresa
        return super().form_valid(form)


class HtmxResponseMixin:
    """
    View mixin that returns partial template for HTMX requests,
    full page template for normal requests.
    """

    partial_template_name = None

    def get_template_names(self):
        if self.request.htmx and self.partial_template_name:
            return [self.partial_template_name]
        return super().get_template_names()
