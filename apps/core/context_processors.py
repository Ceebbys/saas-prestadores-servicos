def empresa_context(request):
    """Add empresa to template context globally."""
    return {
        "current_empresa": getattr(request, "empresa", None),
    }


def notifications_context(request):
    """Provê `notifications_unread_count` para o badge do bell no topbar.

    Tolerante a estados sem auth ou app ainda não migrado (durante setup).
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"notifications_unread_count": 0}
    try:
        from apps.communications.models import Notification
        count = Notification.objects.filter(
            user=user, read_at__isnull=True,
        ).count()
    except Exception:
        count = 0
    return {"notifications_unread_count": count}
