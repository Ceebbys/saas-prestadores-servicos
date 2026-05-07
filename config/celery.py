"""Celery app instance + beat schedule.

Carregado por config/__init__.py para que `celery -A config worker` e
`celery -A config beat` encontrem a app.
"""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

# Define o módulo de settings antes de criar o app.
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", os.getenv("DJANGO_SETTINGS_MODULE", "config.settings.dev")
)

app = Celery("saas_prestadores")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "chatbot-triggers-every-5-min": {
        "task": "apps.chatbot.tasks.run_triggers",
        "schedule": crontab(minute="*/5"),
    },
}


@app.task(bind=True)
def debug_task(self):
    """Sanity check task: `celery -A config call config.celery.debug_task`."""
    print(f"Request: {self.request!r}")
