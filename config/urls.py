from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthcheck(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz/", healthcheck, name="healthcheck"),
    path("admin/", admin.site.urls),
    path("", include("apps.dashboard.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("crm/", include("apps.crm.urls")),
    path("proposals/", include("apps.proposals.urls")),
    path("contracts/", include("apps.contracts.urls")),
    path("operations/", include("apps.operations.urls")),
    path("finance/", include("apps.finance.urls")),
    path("settings/", include("apps.settings_app.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # urlpatterns += [
    #     path("__debug__/", include("debug_toolbar.urls")),
    #     path("__reload__/", include("django_browser_reload.urls")),
    # ]
    pass
