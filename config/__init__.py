"""Project package.

Garante que a Celery app seja importada quando o Django inicia, para que
`@shared_task` decorators sejam registrados antes de qualquer chamada.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
