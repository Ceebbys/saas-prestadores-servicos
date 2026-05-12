"""Decoradores compartilhados — rate limiting, etc. (RV06).

`rate_limit_per_user`:
- Conta requests por (user_id, view_name) numa janela deslizante.
- Backend: cache Django (`django.core.cache`). Funciona com locmem em dev
  e Redis em prod (já configurado).
- Em caso de exceder o limite, retorna `JsonResponse({"error": ...}, status=429)`
  com header `Retry-After`.
- Para usuários não autenticados, não aplica limit (deixa o middleware
  de auth decidir o que fazer).
"""
from __future__ import annotations

import functools
import time
from typing import Callable

from django.core.cache import cache
from django.http import HttpRequest, JsonResponse


def rate_limit_per_user(max_calls: int = 60, window: int = 60) -> Callable:
    """Limita `max_calls` por `window` segundos por usuário e por view.

    Uso::

        @rate_limit_per_user(max_calls=60, window=60)
        def my_view(request): ...

    Em métodos de class-based views, usar via `method_decorator`::

        @method_decorator(rate_limit_per_user(60, 60), name="dispatch")
        class MyView(View): ...
    """

    def decorator(view_func: Callable) -> Callable:
        @functools.wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs):
            user = getattr(request, "user", None)
            if not user or not user.is_authenticated:
                # Não autenticado — deixa o sistema de auth lidar
                return view_func(request, *args, **kwargs)

            # Nome estável para a chave do cache. method_decorator wrappa em
            # functools.partial, que não tem __qualname__; nesses casos
            # extraímos o nome do método interno. Trocamos chars que
            # memcached rejeita (espaços, dois-pontos extras, etc.) por '_'.
            view_name = (
                getattr(view_func, "__qualname__", None)
                or getattr(view_func, "__name__", None)
            )
            if not view_name and hasattr(view_func, "func"):
                # functools.partial → .func tem o método/função wrappada
                inner = view_func.func  # type: ignore[attr-defined]
                view_name = (
                    getattr(inner, "__qualname__", None)
                    or getattr(inner, "__name__", None)
                )
            if not view_name:
                view_name = "anonymous"
            # Sanitiza chars não-ascii e espaços para chave de cache
            view_name = "".join(
                c if c.isalnum() or c in ".-_" else "_" for c in view_name
            )[:120]
            now = int(time.time())
            window_start = now - window
            key = f"ratelimit:{user.id}:{view_name}"

            # Lista de timestamps recentes (sliding window)
            timestamps: list[int] = cache.get(key, [])
            # Remove antigos
            timestamps = [t for t in timestamps if t > window_start]
            if len(timestamps) >= max_calls:
                # Cabou — retornar 429
                retry_after = max(1, (timestamps[0] + window) - now)
                resp = JsonResponse(
                    {
                        "error": "rate_limited",
                        "message": (
                            f"Você excedeu {max_calls} requisições em {window}s. "
                            f"Tente novamente em {retry_after}s."
                        ),
                        "retry_after": retry_after,
                    },
                    status=429,
                )
                resp["Retry-After"] = str(retry_after)
                return resp

            timestamps.append(now)
            cache.set(key, timestamps, timeout=window + 5)
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
