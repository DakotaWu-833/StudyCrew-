"""Environment-driven Django settings for local development and production."""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise ImproperlyConfigured(f"Required environment variable {name} is not set.")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, "true" if default else "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


ENVIRONMENT = env("DJANGO_ENVIRONMENT", "development").lower()
DEBUG = env_bool("DJANGO_DEBUG", ENVIRONMENT == "development")

_development_secret = "development-only-key-change-before-production"
SECRET_KEY = env("DJANGO_SECRET_KEY", _development_secret)
if ENVIRONMENT == "production" and SECRET_KEY == _development_secret:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in production.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "accounts.apps.AccountsConfig",
    "projects.apps.ProjectsConfig",
    "tasks.apps.TasksConfig",
    "meetings.apps.MeetingsConfig",
    "activity.apps.ActivityConfig",
    "integrations.apps.IntegrationsConfig",
    "web.apps.WebConfig",
    "api.apps.ApiConfig",
    "campus.apps.CampusConfig",
    "coordination.apps.CoordinationConfig",
    "operations.apps.OperationsConfig",
    "recruiting.apps.RecruitingConfig",
    "documents_store.apps.DocumentsStoreConfig",
    "learning_exchange.apps.LearningExchangeConfig",
    "project_chat.apps.ProjectChatConfig",
    "offline_sync.apps.OfflineSyncConfig",
    "productivity.apps.ProductivityConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "documents_store.middleware.PrivateUploadLimitMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.UserTimezoneMiddleware",
    "operations.middleware.OperationsMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "web.context_processors.navigation_context",
                "web.context_processors.site_asset_versions",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DB_ENGINE = env("DB_ENGINE", "sqlite").lower()
if DB_ENGINE == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME"),
            "USER": env("DB_USER"),
            "PASSWORD": env("DB_PASSWORD"),
            "HOST": env("DB_HOST", "127.0.0.1"),
            "PORT": env("DB_PORT", "5432"),
            "CONN_MAX_AGE": int(env("DB_CONN_MAX_AGE", "60")),
            "OPTIONS": {"connect_timeout": 5},
        }
    }
else:
    _sqlite_path = BASE_DIR / env("SQLITE_PATH", "var/studycrew.sqlite3")
    _sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": _sqlite_path,
            "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
        }
    }

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "accounts.validators.ComplexityPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

LANGUAGE_CODE = "en-au"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "var" / "static"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / env("MEDIA_PATH", "var/media")

# These uploads are served only through current-project-membership checks.
PROJECT_FILE_MAX_BYTES = int(env("PROJECT_FILE_MAX_BYTES", str(10 * 1024 * 1024)))
PROJECT_FILE_QUOTA_BYTES = int(env("PROJECT_FILE_QUOTA_BYTES", str(250 * 1024 * 1024)))
PROJECT_FILE_DAILY_BYTES = int(env("PROJECT_FILE_DAILY_BYTES", str(100 * 1024 * 1024)))
PROJECT_FILE_DAILY_UPLOADS = int(env("PROJECT_FILE_DAILY_UPLOADS", "30"))
PROJECT_FILE_ZIP_EXPANDED_BYTES = int(env("PROJECT_FILE_ZIP_EXPANDED_BYTES", str(50 * 1024 * 1024)))
PROJECT_FILES_CLAMSCAN = env("PROJECT_FILES_CLAMSCAN", "")
PROJECT_FILES_REQUIRE_SCAN = env_bool("PROJECT_FILES_REQUIRE_SCAN", ENVIRONMENT == "production")
if ENVIRONMENT == "production" and not PROJECT_FILES_REQUIRE_SCAN:
    raise ImproperlyConfigured("Production project uploads require malware scanning.")
if PROJECT_FILES_REQUIRE_SCAN and not PROJECT_FILES_CLAMSCAN:
    raise ImproperlyConfigured("Configure PROJECT_FILES_CLAMSCAN before enabling project uploads with required scanning.")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "web:dashboard"

# Server-side sessions are invalidated on logout and expire after inactivity.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = int(env("SESSION_IDLE_TIMEOUT_SECONDS", "1800"))
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # JavaScript reads this value and sends X-CSRFToken.
CSRF_COOKIE_SAMESITE = "Lax"

EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    "django.core.mail.backends.filebased.EmailBackend",
)
EMAIL_FILE_PATH = BASE_DIR / env("EMAIL_FILE_PATH", "var/emails")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "StudyCrew <noreply@studycrew.local>")
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_TIMEOUT = int(env("EMAIL_TIMEOUT", "10"))
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", f"https://{ALLOWED_HOSTS[0]}" if ENVIRONMENT == "production" and ALLOWED_HOSTS else "http://127.0.0.1:8000").rstrip("/")
from urllib.parse import urlsplit
_public_origin = urlsplit(PUBLIC_BASE_URL)
if (_public_origin.scheme not in {"http", "https"} or not _public_origin.hostname or
        _public_origin.username or _public_origin.password or _public_origin.path or _public_origin.query or _public_origin.fragment):
    raise ImproperlyConfigured("PUBLIC_BASE_URL must be an HTTP(S) origin without credentials, paths or query strings.")
MAIL_MESSAGE_DOMAIN = env("MAIL_MESSAGE_DOMAIN", "studycrew.local")
MAIL_DAILY_LIMIT = int(env("MAIL_DAILY_LIMIT", "2000"))
MAIL_RETENTION_DAYS = int(env("MAIL_RETENTION_DAYS", "30"))
BACKUP_ROOT = Path(env("BACKUP_ROOT", str(BASE_DIR / "var" / "backups")))
BACKUP_MAX_AGE_HOURS = int(env("BACKUP_MAX_AGE_HOURS", "30"))
if not 1 <= BACKUP_MAX_AGE_HOURS <= 168:
    raise ImproperlyConfigured("BACKUP_MAX_AGE_HOURS must be between 1 and 168.")
MAIL_WEBHOOK_SECRET = env("MAIL_WEBHOOK_SECRET", "")
ASYNC_EXPORTS = env_bool("ASYNC_EXPORTS", ENVIRONMENT == "production")
ASYNC_REMINDERS = env_bool("ASYNC_REMINDERS", ENVIRONMENT == "production")
OPERATIONS_RATE_LIMITS = env_bool("OPERATIONS_RATE_LIMITS", True)
SERVICE_CONTACT_EMAIL = env("SERVICE_CONTACT_EMAIL", "")
MAINTENANCE_MODE = env_bool("MAINTENANCE_MODE", False)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "api.authentication.MFASessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "api.exceptions.safe_exception_handler",
    "PAGE_SIZE": 50,
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "NUM_PROXIES": int(env("TRUSTED_PROXY_COUNT", "1" if ENVIRONMENT == "production" else "0")),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "StudyCrew REST API",
    "DESCRIPTION": "Versioned API for project, task, meeting and collaboration workflows.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "ENUM_NAME_OVERRIDES": {
        "InvitationStatusEnum": "api.serializers.INVITATION_STATUS_CHOICES",
        "TaskStatusEnum": "api.serializers.TASK_STATUS_CHOICES",
        "TaskPriorityEnum": "api.serializers.TASK_PRIORITY_CHOICES",
        "MembershipRoleEnum": "api.serializers.MEMBERSHIP_ROLE_CHOICES",
        "MutableMembershipRoleEnum": "api.serializers.MUTABLE_MEMBERSHIP_ROLE_CHOICES",
        "DeliveryStatusEnum": "operations.serializers.DELIVERY_STATUS_CHOICES",
        "SupportStatusEnum": "operations.serializers.SUPPORT_STATUS_CHOICES",
    },
}

# Bound request sizes and sensitive-operation limits.
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 300
LOGIN_FAILURE_LIMIT = int(env("LOGIN_FAILURE_LIMIT", "5"))
LOGIN_FAILURE_WINDOW_SECONDS = int(env("LOGIN_FAILURE_WINDOW_SECONDS", "900"))
LOGIN_LOCKOUT_SECONDS = int(env("LOGIN_LOCKOUT_SECONDS", "900"))
OTP_TTL_SECONDS = int(env("OTP_TTL_SECONDS", "600"))
OTP_MAX_ATTEMPTS = int(env("OTP_MAX_ATTEMPTS", "5"))
EXTERNAL_API_TIMEOUT_SECONDS = float(env("EXTERNAL_API_TIMEOUT_SECONDS", "3"))
NAGER_DATE_CACHE_TTL_SECONDS = int(env("NAGER_DATE_CACHE_TTL_SECONDS", "86400"))
USE_X_ACCEL_REDIRECT = env_bool("USE_X_ACCEL_REDIRECT", ENVIRONMENT == "production")

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

if ENVIRONMENT == "production":
    if DEBUG:
        raise ImproperlyConfigured("DJANGO_DEBUG must be false in production.")
    if len(SECRET_KEY) < 50 or SECRET_KEY.lower().startswith(("replace", "change")):
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a random value of at least 50 characters.")
    if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
        raise ImproperlyConfigured("Production requires explicit DJANGO_ALLOWED_HOSTS values.")
    if _public_origin.scheme != "https" or _public_origin.hostname not in ALLOWED_HOSTS:
        raise ImproperlyConfigured("Production PUBLIC_BASE_URL must use HTTPS and an allowed host.")
    if not CSRF_TRUSTED_ORIGINS or any(
        not origin.startswith("https://") for origin in CSRF_TRUSTED_ORIGINS
    ):
        raise ImproperlyConfigured(
            "Production requires explicit HTTPS DJANGO_CSRF_TRUSTED_ORIGINS values."
        )
    if DB_ENGINE != "postgresql":
        raise ImproperlyConfigured("Production must use the restricted PostgreSQL role.")
    if EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
        raise ImproperlyConfigured("Production MFA requires the SMTP email backend.")
    if not EMAIL_HOST or not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD:
        raise ImproperlyConfigured("Production SMTP host, username and password are required.")
    if not USE_X_ACCEL_REDIRECT:
        raise ImproperlyConfigured("Production downloads must use Nginx X-Accel-Redirect.")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
        "server": {"()": "django.utils.log.ServerFormatter", "format": "[{server_time}] {message}", "style": "{"},
    },
    "filters": {"sensitive_urls": {"()": "config.logging.SensitiveURLFilter"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard", "filters": ["sensitive_urls"]},
        "server": {"class": "logging.StreamHandler", "formatter": "server", "level": "INFO", "filters": ["sensitive_urls"]},
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        # Django installs its defaults before this dictionary. Replace the
        # inherited unfiltered handlers as well as runserver's separate handler.
        "django": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO"), "propagate": False},
        "django.server": {"handlers": ["server"], "level": "INFO", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
