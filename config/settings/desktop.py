"""
Settings used when the application runs inside the packaged PySide6 desktop
shell (served locally via Waitress). Imported by desktop/main.py before the
server starts.
"""

from .base import *  # noqa: F401,F403

import os

from django.core.management.utils import get_random_secret_key

from config.runtime import get_app_data_dir, is_frozen

# The packaged build must never run with DEBUG on: it would leak tracebacks
# to the local QWebEngineView and slow down template rendering. Source runs
# (python -m desktop.main) keep DEBUG on, exactly as before.
DEBUG = not is_frozen()

# Still local-only -- the Waitress server only ever binds to 127.0.0.1.
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']


def _load_or_create_secret_key(path):
    """
    One random SECRET_KEY per installation, stored next to the database so it
    survives application updates (sessions stay valid) and is never shared
    between customers.
    """
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if len(existing) >= 50:
            return existing
    except FileNotFoundError:
        pass

    key = get_random_secret_key()
    try:
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(key)
    except FileExistsError:
        # Empty/short leftover file: replace it.
        path.write_text(key, encoding="utf-8")
    return key


# ---------------------------------------------------------------------------
# Persistent customer data (see config/runtime.py)
#
# In a PyInstaller build the application directory is replaced on every
# update and may be read-only, so the SQLite database, its backups, logs and
# the secret key live under %LOCALAPPDATA%\140JahanPour instead. Source
# runs without FUELSTATION_DATA_DIR keep using BASE_DIR/db.sqlite3.
# ---------------------------------------------------------------------------
APP_DATA_DIR = get_app_data_dir()

if APP_DATA_DIR is not None:
    DATABASES["default"]["NAME"] = APP_DATA_DIR / "db.sqlite3"  # noqa: F405

    BACKUP_DIR = APP_DATA_DIR / "backups"
    LOG_DIR = APP_DATA_DIR / "logs"
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    SECRET_KEY = _load_or_create_secret_key(APP_DATA_DIR / "secret_key.txt")

    # A windowed packaged app has no console, so errors would otherwise
    # vanish. Keep a small rotating log next to the data.
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
            },
        },
        "handlers": {
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(LOG_DIR / "fuelstation.log"),
                "maxBytes": 1_000_000,
                "backupCount": 3,
                "encoding": "utf-8",
                "delay": True,
                "formatter": "standard",
            },
        },
        "root": {"handlers": ["file"], "level": "WARNING"},
        "loggers": {
            "fuelstation": {
                "handlers": ["file"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }

# The packaged/source desktop runtime serves static assets locally through
# WhiteNoise. The actual resource tree is bundled by FuelStation.spec.
