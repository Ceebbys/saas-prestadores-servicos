from .base import *  # noqa: F401, F403

DEBUG = True

INSTALLED_APPS += [  # noqa: F405
    # "debug_toolbar",
    # "django_browser_reload",
    "django_extensions",
]

# MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405
# MIDDLEWARE += ["django_browser_reload.middleware.BrowserReloadMiddleware"]  # noqa: F405

INTERNAL_IPS = ["127.0.0.1"]

# Remove WhiteNoise from middleware in development (it caches files at startup)
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405

# Use SQLite for quick dev if PostgreSQL is not available
import os

if os.getenv("USE_SQLITE", "false").lower() == "true":
    DATABASES = {  # noqa: F405
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
        }
    }

# Disable whitenoise CompressedManifest em dev (recarrega arquivos sem
# precisar de collectstatic toda hora). `default` é OBRIGATÓRIO em
# Django 5+ para qualquer FileField/ImageField funcionar.
STORAGES = {  # noqa: F405
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
