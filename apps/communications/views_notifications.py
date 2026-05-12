"""Views de notificações (Fase 4).

- Listagem + paginação
- Dropdown HTMX para o bell do topbar
- Mark-read individual / mark-all-read
- Web Push: subscribe, unsubscribe, VAPID public key endpoint
"""
from __future__ import annotations

import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from apps.communications.models import Notification, PushSubscription

logger = logging.getLogger(__name__)


def _login_required(view_cls):
    """Decora dispatch da classe com login_required."""
    view_cls.dispatch = method_decorator(login_required)(view_cls.dispatch)
    return view_cls


@_login_required
class NotificationListView(View):
    """Lista todas as notificações do user (paginada).

    GET ?page=1&unread_only=1
    """

    PAGE_SIZE = 20

    def get(self, request):
        from django.core.paginator import Paginator
        qs = (
            Notification.objects
            .filter(user=request.user)
            .order_by("-created_at")
        )
        if request.GET.get("unread_only") == "1":
            qs = qs.filter(read_at__isnull=True)
        paginator = Paginator(qs, self.PAGE_SIZE)
        page_number = request.GET.get("page", 1)
        try:
            page_number = int(page_number)
        except (TypeError, ValueError):
            page_number = 1
        page = paginator.get_page(page_number)

        unread_count = Notification.objects.filter(
            user=request.user, read_at__isnull=True,
        ).count()

        return render(request, "communications/notifications_list.html", {
            "page_obj": page,
            "notifications": page.object_list,
            "unread_count": unread_count,
            "unread_only": request.GET.get("unread_only") == "1",
        })


@_login_required
class NotificationDropdownView(View):
    """Partial HTMX para o bell — últimas 10 notificações + badge."""

    LIMIT = 10

    def get(self, request):
        notifications = list(
            Notification.objects
            .filter(user=request.user)
            .order_by("-created_at")[: self.LIMIT]
        )
        unread_count = Notification.objects.filter(
            user=request.user, read_at__isnull=True,
        ).count()
        return render(request, "communications/partials/_notification_dropdown.html", {
            "notifications": notifications,
            "unread_count": unread_count,
        })


@_login_required
class NotificationMarkReadView(View):
    """POST — marca notificação como lida. Retorna 204."""

    def post(self, request, pk: int):
        n = Notification.objects.filter(pk=pk, user=request.user).first()
        if n is None:
            return HttpResponse(status=404)
        if n.read_at is None:
            n.mark_read()
        return HttpResponse(status=204)


@_login_required
class NotificationMarkAllReadView(View):
    """POST — marca todas como lidas.

    Se HTMX: retorna o dropdown atualizado (zerado).
    Senão: retorna JSON {"ok": True, "updated": N}.
    """

    def post(self, request):
        from django.utils import timezone
        updated = Notification.objects.filter(
            user=request.user, read_at__isnull=True,
        ).update(read_at=timezone.now())

        if request.htmx:
            # Retorna o dropdown atualizado (badge=0, todas lidas)
            notifications = list(
                Notification.objects
                .filter(user=request.user)
                .order_by("-created_at")[: NotificationDropdownView.LIMIT]
            )
            return render(
                request,
                "communications/partials/_notification_dropdown.html",
                {"notifications": notifications, "unread_count": 0},
            )
        return JsonResponse({"ok": True, "updated": updated})


# ---------------------------------------------------------------------------
# Web Push (VAPID)
# ---------------------------------------------------------------------------


@_login_required
class VapidPublicKeyView(View):
    """GET — retorna chave pública VAPID para o browser registrar push."""

    def get(self, request):
        from django.conf import settings
        public_key = getattr(settings, "VAPID_PUBLIC_KEY", "")
        if not public_key:
            return JsonResponse({"enabled": False})
        return JsonResponse({"enabled": True, "publicKey": public_key})


@_login_required
class PushSubscribeView(View):
    """POST — registra uma PushSubscription enviada pelo service worker.

    Body JSON:
        {
            "endpoint": str,
            "keys": {"p256dh": str, "auth": str}
        }
    """

    def post(self, request):
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return HttpResponseBadRequest("invalid_json")

        endpoint = (payload.get("endpoint") or "").strip()
        keys = payload.get("keys") or {}
        p256dh = (keys.get("p256dh") or "").strip()
        auth = (keys.get("auth") or "").strip()
        if not (endpoint and p256dh and auth):
            return HttpResponseBadRequest("missing_fields")

        # UPSERT: se já existe esse endpoint, atualiza dono e chaves
        sub, _ = PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                "user": request.user,
                "p256dh": p256dh,
                "auth": auth,
                "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:300],
            },
        )
        return JsonResponse({"ok": True, "id": sub.pk})


@_login_required
class PushUnsubscribeView(View):
    """POST — remove PushSubscription do endpoint informado."""

    def post(self, request):
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return HttpResponseBadRequest("invalid_json")
        endpoint = (payload.get("endpoint") or "").strip()
        if not endpoint:
            return HttpResponseBadRequest("missing_endpoint")
        deleted, _ = PushSubscription.objects.filter(
            user=request.user, endpoint=endpoint,
        ).delete()
        return JsonResponse({"ok": True, "deleted": deleted})
