"""Django settings for the PoliticalAgent public site and identity service."""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# One repo-root .env, exactly as `agentic_backend/src/config.py` resolves it. Django does
# not read a .env on its own, so this must actually be loaded, not merely
# named: under Compose the values arrive through `env_file` and this is a
# no-op, but `manage.py migrate` run from a shell has nothing else.
REPO_ROOT_ENV = BASE_DIR.parent / ".env"
load_dotenv(REPO_ROOT_ENV)

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [h for h in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if h]
CSRF_TRUSTED_ORIGINS = [
    o for o in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

# The one public origin: canonical links, Open Graph URLs, JSON-LD and the
# sitemap are built from it. Templates read this, not the `sites` row: that
# costs a DB query per page and the landing tests render without a database.
# `pages` migration 0001 copies it into the `sites` row for the sitemap and allauth.
SITE_ORIGIN = "https://politicalagent.eu"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.sitemaps",
    "allauth",
    "allauth.account",
    "users",
    # The public server-rendered pages (`/` and, in unit 12, the blog). No
    # models and no signals: the template layer only.
    "pages.apps.PagesConfig",
    "blog.apps.BlogConfig",
    # NOT the bare "chat": `ChatConfig.ready()` is what imports `signals.py`,
    # and without that import the `pre_delete` receiver is never connected —
    # deleting a user would silently leave every one of their messages in the
    # checkpointer tables. A dead GDPR path that raises nothing and logs
    # nothing.
    "chat.apps.ChatConfig",
    # Raw-SQL, read-only admin browse pages over the four tables LangGraph's
    # checkpointer owns in `agentic`. Django defines no models for them; the
    # schema is Alembic's business, the deletes are `chat`'s signals.
    "checkpointer.apps.CheckpointerConfig",
    # The outgoing-mail queue: every Django email lands in its `emails_email`
    # table first (see `emails/services.py`).
    "emails",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "politicalagent.urls"
WSGI_APPLICATION = "politicalagent.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Listed before APP_DIRS so `templates/account/*.html` overrides
        # allauth's own copies (allauth docs, common/templates.html).
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "pages.context_processors.site_origin",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.getenv("POSTGRES_HOST", "postgres"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
SITE_ID = 1

# Email-only identity: no username anywhere, and an account is unusable until
# the address is verified (Q16 — this is what gives the daily quota its teeth).
AUTH_USER_MODEL = "users.User"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# Valid ONLY because AUTH_USER_MODEL above has no username field. Against
# Django's stock `auth.User` this setting is a production bug: allauth's docs
# list it under "Custom User Models", and with the stock model (username
# unique, blank=False) allauth stops populating username, so the first signup
# stores "" and the SECOND one dies on the unique index with a 500 — after a
# password was accepted and before any mail is sent. A one-signup smoke test
# passes. See the plan's §7 for why the custom model is a unit-1 decision.
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_UNIQUE_EMAIL = True

# allauth ships rate limits by default (signup 20/m/ip, login 30/m/ip,
# login_failed 10/m/ip + 5/5m/key). They run on Django's cache, and the default
# cache is per-process LocMemCache, which resets on restart and is not shared
# between workers. Naming it here rather than inheriting it silently.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}
LOGIN_REDIRECT_URL = "/chat"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"

# `rest_framework` is deliberately NOT added to INSTALLED_APPS. `AccessToken`
# reaches only simplejwt's `tokens.py` and `settings.py`; the app registry
# entry buys nothing when no DRF view, serializer or template is used.

SIMPLE_JWT = {
    # Shared with `agentic_backend/` through the environment, and deliberately NOT
    # Django's SECRET_KEY: the API only ever needs to *verify*, and must
    # never hold a key that can also sign a session cookie.
    "SIGNING_KEY": os.environ["JWT_SIGNING_KEY"],
    "ALGORITHM": "HS256",
    # Checked once at request start, so a stream may outlive the token: the
    # frontend's 15-minute stream cap does not depend on it.
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_HEADER_TYPES": ("Bearer",),
}
ACCESS_TOKEN_SECONDS = int(SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())

# Q20: mailers. The `default` mailer is the queue — every email Django
# sends (allauth included) is stored in `emails_email` and sent later by
# `emails.services.send_batch` through the `smtp` mailer, which holds the
# domain mailbox over SMTP. Switching to a relay later is an `smtp` change.
SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
# An empty value means the default, not a broken backend.
_DJANGO_EMAIL_BACKEND = os.getenv("DJANGO_EMAIL_BACKEND") or SMTP_BACKEND
MAILERS = {
    "default": {"BACKEND": "emails.backend.QueueBackend"},
    "smtp": {
        "BACKEND": _DJANGO_EMAIL_BACKEND,
        # OPTIONS must match the backend: Django raises InvalidMailer for
        # options an overridden backend does not accept (the console backend,
        # for example).
        "OPTIONS": {
            **(
                {
                    "host": os.getenv("EMAIL_HOST", ""),
                    "port": int(os.getenv("EMAIL_PORT", "587")),
                    "username": os.getenv("EMAIL_HOST_USER", ""),
                    "password": os.getenv("EMAIL_HOST_PASSWORD", ""),
                    "use_tls": os.getenv("EMAIL_USE_TLS", "true").lower()
                    == "true",
                    # A hung SMTP host must not block the batch (and its row
                    # locks) forever: `EMAIL_TIMEOUT` defaults to 30 s.
                    "timeout": int(os.getenv("EMAIL_TIMEOUT", "30")),
                }
                if _DJANGO_EMAIL_BACKEND == SMTP_BACKEND
                else {}
            ),
        },
    },
}
# The most mail the sender hands to OVH in any 60 minutes; OVH's real limit
# is unconfirmed (a forum post reports 200 per hour per mailbox).
EMAIL_MAX_PER_HOUR = int(os.getenv("EMAIL_MAX_PER_HOUR", "100"))
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@politicalagent.eu")

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# Behind nginx TLS in production.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"

# Sent on HTTPS responses only (SecurityMiddleware); host-wide once a browser
# sees it. No includeSubDomains or preload: both are hard to undo.
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
