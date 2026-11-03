"""
Runtime location of the customer's mutable data (SQLite database, backups,
logs, per-installation secret key).

Rule: customer data NEVER lives inside the application files. In a packaged
(PyInstaller) build the application directory -- and the temporary/bundle
directory inside it -- is replaced wholesale by every update, so anything
stored there would be lost. Mutable data therefore lives in a per-user data
directory that the installer/uninstaller and any new application version
never touch:

    %LOCALAPPDATA%\\140JahanPour\\
        db.sqlite3          the customer's accounting database
        backups\\            automatic pre-migration copies of db.sqlite3
        logs\\               application / startup-error logs
        secret_key.txt      per-installation Django SECRET_KEY

The folder name must stay "140JahanPour": changing it would make an updated
version look at an empty location and silently "lose" existing customer data.

Source/development runs (not frozen, no override) return None and keep using
BASE_DIR / db.sqlite3 exactly as before.

FUELSTATION_DATA_DIR may be set to force a different data directory. It is
meant for smoke-testing a build against a throw-away database; customers
never set it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_FOLDER_NAME = "140JahanPour"
DATA_DIR_ENV_VAR = "FUELSTATION_DATA_DIR"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def _bundle_directories() -> list[Path]:
    """Directories that belong to the packaged application and get replaced
    on update: the executable's folder and PyInstaller's internal folder."""
    directories = [Path(sys.executable).resolve().parent]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        directories.append(Path(meipass).resolve())
    return directories


def _assert_outside_application_files(data_dir: Path) -> None:
    resolved = data_dir.resolve()
    for bundle_dir in _bundle_directories():
        if resolved == bundle_dir or bundle_dir in resolved.parents:
            raise RuntimeError(
                f"Refusing to keep customer data inside the application "
                f"directory ({bundle_dir}); it is replaced on update. "
                f"Data directory was: {resolved}"
            )


def get_app_data_dir() -> Path | None:
    """
    Return (and create) the persistent customer-data directory, or None for
    a plain source run where the development layout is used.
    """
    override = os.environ.get(DATA_DIR_ENV_VAR)
    if override:
        data_dir = Path(override).expanduser()
    elif is_frozen():
        local_app_data = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        )
        data_dir = local_app_data / APP_FOLDER_NAME
    else:
        return None

    if is_frozen():
        _assert_outside_application_files(data_dir)

    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
