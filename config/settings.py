import os
from pathlib import Path
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
SECRET_KEY = os.getenv("SECRET_KEY", "development-only-fuelroute-key-do-not-deploy")
if not DEBUG and (SECRET_KEY.startswith("development-only") or len(SECRET_KEY) < 32):
    raise ImproperlyConfigured("Set a unique SECRET_KEY when DEBUG=false")
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "routing",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "routing.middleware.TimingMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": ["django.template.context_processors.request"]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("DATABASE_PATH", str(BASE_DIR / "db.sqlite3")),
        "OPTIONS": {"timeout": 30},
    }
}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "fuelroute_cache",
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "30/min"},
    "EXCEPTION_HANDLER": "routing.exceptions.exception_handler",
}
OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org")
GEOCODER_URL = os.getenv("GEOCODER_URL", "https://nominatim.openstreetmap.org")
GEOCODER_USER_AGENT = os.getenv(
    "GEOCODER_USER_AGENT", "FuelRouteAssessment/1.0 (local evaluation)"
)
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "25"))
CORRIDOR_MILES = float(os.getenv("CORRIDOR_MILES", "2"))
DETOUR_FACTOR = float(os.getenv("DETOUR_FACTOR", "1.5"))
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "300"))
SOLVER_SECONDS = float(os.getenv("SOLVER_SECONDS", "15"))
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "false").lower() == "true"
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"routing": {"handlers": ["console"], "level": "INFO"}},
}

if (
    CORRIDOR_MILES <= 0
    or DETOUR_FACTOR < 1
    or MAX_CANDIDATES < 1
    or SOLVER_SECONDS <= 0
    or HTTP_TIMEOUT <= 0
):
    raise ImproperlyConfigured(
        "Invalid routing limits: use positive limits and DETOUR_FACTOR >= 1"
    )
