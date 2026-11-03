"""
Base Django settings for the Fuel Station Management App (140 Jahan Pour).

This file holds settings shared across all run modes. `desktop.py` extends
this for the packaged PySide6 desktop runtime.
"""

from pathlib import Path

# config/settings/base.py -> project root is two parents up
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: replace with a securely generated value before packaging
# for distribution; do not reuse this development key in production builds.
SECRET_KEY = 'django-insecure-!s%0%eh4ki$_)+50irs^m)^$o+do0(lp2gl-aq=@u^7x!$!^8'

# Desktop settings module flips this off for the packaged build.
DEBUG = True

# Local-only desktop app: the Django server is never reachable except from
# the PySide6 shell on the same machine.
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Project apps — one per bounded business concept (see architecture doc).
    'apps.core',
    'apps.accounts',
    'apps.license',
    'apps.stations',
    'apps.workday',
    'apps.sales',
    'apps.purchases',
    'apps.inventory',
    'apps.seals',
    'apps.deposits',
    'apps.statement',
    'apps.comparison',
    'apps.reports',
    'apps.printing',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Enforces license validity on every request except the license page
    # itself (exempted internally to avoid a redirect loop). See
    # apps/license/middleware.py.
    'apps.license.middleware.LicenseEnforcementMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.core.context_processors.global_header_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database — SQLite, per architecture: single-file, zero-config, more than
# sufficient for one station's daily accounting volume.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization — Persian, RTL.
LANGUAGE_CODE = 'fa'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
# The desktop app is local-only. WhiteNoise serves the small static tree
# directly from Django's staticfile finders, so the packaged build does not
# require a separate web server or a manual collectstatic step at runtime.
WHITENOISE_USE_FINDERS = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Login flow
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'core:dashboard'
LOGOUT_REDIRECT_URL = 'accounts:login'

# ---------------------------------------------------------------------------
# Project-specific constants
# ---------------------------------------------------------------------------

# Fixed license duration in days (see architecture doc). A future renewal
# mechanism may make this configurable per-renewal without changing this
# default.
LICENSE_DEFAULT_DURATION_DAYS = 365

# Days before expiry at which the in-app warning starts appearing.
LICENSE_WARNING_THRESHOLD_DAYS = 7
