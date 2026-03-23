from django.shortcuts import redirect
from django.urls import reverse


# URLs that don't require empresa context
EXEMPT_URLS = [
    "/accounts/login/",
    "/accounts/logout/",
    "/accounts/register/",
    "/admin/",
    "/__debug__/",
    "/__reload__/",
]


class EmpresaMiddleware:
    """
    Sets request.empresa from the authenticated user's active_empresa.
    Redirects to empresa selection if user has no active empresa.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.empresa = None

        if request.user.is_authenticated:
            if request.user.active_empresa:
                request.empresa = request.user.active_empresa
            elif not any(request.path.startswith(url) for url in EXEMPT_URLS):
                # User is authenticated but has no active empresa
                # Try to set the first available empresa
                from apps.accounts.models import Membership

                membership = (
                    Membership.objects.filter(user=request.user, is_active=True)
                    .select_related("empresa")
                    .first()
                )
                if membership:
                    request.user.active_empresa = membership.empresa
                    request.user.save(update_fields=["active_empresa"])
                    request.empresa = membership.empresa
                elif not request.path.startswith("/accounts/"):
                    return redirect(reverse("accounts:register"))

        return self.get_response(request)
