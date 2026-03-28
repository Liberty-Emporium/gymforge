"""
GymForge — Production Settings (Railway)
"""
from .base import *
import os
import dj_database_url
from decouple import config

DEBUG = os.environ.get('DJANGO_DEBUG', '') == 'True'

ALLOWED_HOSTS = [
    '.gymforge.com',
    'gymforge.com',
    '.railway.app',
    config('RAILWAY_PUBLIC_DOMAIN', default=''),
]

# Fall back to public schema when the request domain isn't in GymDomain
# (covers the Railway preview URL and any unregistered domains)
SHOW_PUBLIC_IF_NO_TENANT_FOUND = True

# ---------------------------------------------------------------------------
# Database — Railway provides DATABASE_URL automatically
# ---------------------------------------------------------------------------
_raw_db_url = os.environ.get('DATABASE_URL', '')
if _raw_db_url:
    # Parse the URL directly; keep the django-tenants engine
    _db_from_env = dj_database_url.parse(_raw_db_url, conn_max_age=600, conn_health_checks=True)
    DATABASES['default'].update({
        'NAME': _db_from_env['NAME'],
        'USER': _db_from_env['USER'],
        'PASSWORD': _db_from_env['PASSWORD'],
        'HOST': _db_from_env['HOST'],
        'PORT': _db_from_env['PORT'],
        'CONN_MAX_AGE': 600,
        'CONN_HEALTH_CHECKS': True,
    })

# ---------------------------------------------------------------------------
# Static Files — whitenoise
# ---------------------------------------------------------------------------
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# ---------------------------------------------------------------------------
# File Storage — Cloudflare R2
# ---------------------------------------------------------------------------
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'

# ---------------------------------------------------------------------------
# Celery — run tasks synchronously (no worker/Redis needed for demo)
# ---------------------------------------------------------------------------
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
