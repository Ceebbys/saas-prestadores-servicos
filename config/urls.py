from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from apps.proposals.views import ProposalPublicView


def healthcheck(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz/", healthcheck, name="healthcheck"),
    path("admin/", admin.site.urls),
    # Visualização pública de proposta via token (cliente final, sem auth).
    # Mantida fora de /proposals/ para evitar leak da estrutura interna.
    path("p/<uuid:token>/", ProposalPublicView.as_view(), name="proposal_public"),
    path("", include("apps.dashboard.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("crm/", include("apps.crm.urls")),
    path("contacts/", include("apps.contacts.urls")),
    path("proposals/", include("apps.proposals.urls")),
    path("contracts/", include("apps.contracts.urls")),
    path("operations/", include("apps.operations.urls")),
    path("finance/", include("apps.finance.urls")),
    path("chatbot/", include("apps.chatbot.urls")),
    path("automation/", include("apps.automation.urls")),
    path("settings/", include("apps.settings_app.urls")),
    path("inbox/", include("apps.communications.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # urlpatterns += [
    #     path("__debug__/", include("debug_toolbar.urls")),
    #     path("__reload__/", include("django_browser_reload.urls")),
    # ]
    pass
