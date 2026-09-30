import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "development-only-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "0").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [host for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if host]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "fuelplan.apps.FuelPlanConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]
ROOT_URLCONF = "routefuel.urls"
TEMPLATES = []
WSGI_APPLICATION = "routefuel.wsgi.application"
ASGI_APPLICATION = "routefuel.asgi.application"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "routefuel-response-cache",
        "TIMEOUT": 600,
    }
}

ORS_API_KEY = os.environ.get("ORS_API_KEY", "")
ORS_BASE_URL = os.environ.get("ORS_BASE_URL", "https://api.heigit.org")
ORS_TIMEOUT_SECONDS = float(os.environ.get("ORS_TIMEOUT_SECONDS", "8"))
FUEL_DATA_PATH = Path(os.environ.get("FUEL_DATA_PATH", BASE_DIR / "fuel-prices-for-be-assessment.csv"))
CENSUS_PLACES_PATH = Path(os.environ.get("CENSUS_PLACES_PATH", BASE_DIR / "data/census_places_2025.zip"))
CENSUS_SUBDIVISIONS_PATH = Path(os.environ.get("CENSUS_SUBDIVISIONS_PATH", BASE_DIR / "data/census_cousubs_2025.zip"))
