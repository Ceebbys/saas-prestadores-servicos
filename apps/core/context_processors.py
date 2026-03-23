def empresa_context(request):
    """Add empresa to template context globally."""
    return {
        "current_empresa": getattr(request, "empresa", None),
    }
