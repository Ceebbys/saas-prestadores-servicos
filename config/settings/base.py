import os
from pathlib import Path

from dotenv import load_dotenv

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "insecure-fallback-key")

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# Application definition
INSTALLED_APPS = [
    # Daphne — DEVE vir antes de staticfiles para o runserver usar o
    # ASGI runserver com WebSocket support (django-channels docs).
    "daphne",
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Third party
    "channels",
    "django_htmx",
    # Project apps
    "apps.core",
    "apps.accounts",
    "apps.dashboard",
    "apps.crm",
    "apps.contacts",
    "apps.proposals",
    "apps.contracts",
    "apps.operations",
    "apps.finance",
    "apps.chatbot",
    "apps.automation",
    "apps.settings_app",
    "apps.communications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.core.middleware.EmpresaMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.empresa_context",
                "apps.core.context_processors.notifications_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Channels — realtime (Inbox ao vivo + notificações).
# Em testes/dev sem Redis, usa InMemoryChannelLayer; em produção, Redis.
CHANNELS_REDIS_URL = os.getenv("CHANNELS_REDIS_URL", os.getenv("REDIS_URL", ""))
if CHANNELS_REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [CHANNELS_REDIS_URL]},
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
    }

# Cache padrão — usado pelo lock per-tenant do IMAP poller e por throttling
# do builder. Em dev/test sem Redis, usa LocMemCache; em produção, Redis.
CACHE_REDIS_URL = os.getenv("CACHE_REDIS_URL", os.getenv("REDIS_URL", ""))
if CACHE_REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_REDIS_URL,
        },
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "default-cache",
        },
    }

# Database
import dj_database_url

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(DATABASE_URL, conn_max_age=600),
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "saas_prestadores"),
            "USER": os.getenv("DB_USER", "postgres"),
            "PASSWORD": os.getenv("DB_PASSWORD", "postgres"),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }

# Auth
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Static files
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    # Django 5+: "default" é obrigatório para FileField/ImageField salvar.
    # Sem ele, qualquer upload (ex.: Proposal.header_image) dispara
    # `InvalidStorageError: Could not find config for 'default'` → 500.
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Media files
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Messages
from django.contrib.messages import constants as messages

MESSAGE_TAGS = {
    messages.DEBUG: "debug",
    messages.INFO: "info",
    messages.SUCCESS: "success",
    messages.WARNING: "warning",
    messages.ERROR: "error",
}

# --- Evolution API (WhatsApp) ---
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE_NAME = os.getenv("EVOLUTION_INSTANCE_NAME", "")
EVOLUTION_WEBHOOK_TOKEN = os.getenv("EVOLUTION_WEBHOOK_TOKEN", "")

# --- Celery + Redis ---
CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_TIMEZONE = "America/Sao_Paulo"
CELERY_TASK_ALWAYS_EAGER = (
    os.getenv("CELERY_EAGER", "false").lower() in ("1", "true", "yes")
)
CELERY_TASK_EAGER_PROPAGATES = True
# Beat schedule é importado em config/celery.py para evitar import cycle.

# --- Email (transactional / password reset) ---
# If EMAIL_HOST is empty, emails go to console (dev/staging without SMTP).
# In production, set EMAIL_HOST + EMAIL_HOST_USER + EMAIL_HOST_PASSWORD.
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").lower() in ("1", "true", "yes")
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "false").lower() in ("1", "true", "yes")
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))

if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL", "ServiçoPro <no-reply@cebs-server.cloud>"
)
SERVER_EMAIL = os.getenv("SERVER_EMAIL", DEFAULT_FROM_EMAIL)

# Chave Fernet para criptografar campos sensíveis (senhas SMTP por tenant).
# Gere com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Em DEBUG, se ausente, deriva de SECRET_KEY (apps/core/encryption.py).
FERNET_KEY = os.getenv("FERNET_KEY", "")

# Password reset tokens expire after this many days
PASSWORD_RESET_TIMEOUT = int(os.getenv("PASSWORD_RESET_TIMEOUT_DAYS", "1")) * 24 * 60 * 60

# Public site URL used in transactional emails (full domain incl. scheme).
SITE_URL = os.getenv("SITE_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Web Push (VAPID) — gerar par com:
#   python -m apps.communications.management.commands.generate_vapid
# Em dev/test, ausência das chaves desabilita push (notificações in-app
# continuam funcionando via WebSocket).
# ---------------------------------------------------------------------------
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_CONTACT_EMAIL = os.getenv(
    "VAPID_CONTACT_EMAIL", "admin@servicopro.app",
)

# ---------------------------------------------------------------------------
# RV06 — Limites do construtor visual de fluxos (chatbot builder)
# ---------------------------------------------------------------------------
CHATBOT_BUILDER_MAX_NODES = int(os.getenv("CHATBOT_BUILDER_MAX_NODES", "200"))
CHATBOT_BUILDER_MAX_EDGES = int(os.getenv("CHATBOT_BUILDER_MAX_EDGES", "500"))
CHATBOT_BUILDER_MAX_TEXT_LEN = int(os.getenv("CHATBOT_BUILDER_MAX_TEXT_LEN", "5000"))
CHATBOT_BUILDER_MAX_GRAPH_BYTES = int(os.getenv("CHATBOT_BUILDER_MAX_GRAPH_BYTES", str(512 * 1024)))
CHATBOT_BUILDER_RATE_LIMIT_CALLS = int(os.getenv("CHATBOT_BUILDER_RATE_LIMIT_CALLS", "60"))
CHATBOT_BUILDER_RATE_LIMIT_WINDOW = int(os.getenv("CHATBOT_BUILDER_RATE_LIMIT_WINDOW", "60"))
