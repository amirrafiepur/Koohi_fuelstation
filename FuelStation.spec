# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec -- 140 Jahan Pour Fuel Station Management System.

Windows x86-64, Python 3.11, PyInstaller 6.22.2, onedir + windowed.
Output: dist\\FuelStation\\FuelStation.exe  (what build_windows.ps1 and
installer.iss expect).

Build, from the project root inside the project's Python 3.11 environment:

    py -3.11 manage.py collectstatic --noinput
    py -3.11 -m PyInstaller --clean --noconfirm FuelStation.spec

What goes into the bundle (all verified against the repository):
  * desktop/main.py               entry point (GUI mode, and --server mode:
                                  the same exe relaunches itself to run Waitress)
  * config/ + apps/*              Django project, apps, migrations, management
                                  commands (seed_station), templatetags
  * templates/                    Django templates            (BASE_DIR/templates)
  * static/                       CSS/JS/Vazirmatn fonts      (also read from disk
                                  by WeasyPrint as its base_url)
  * staticfiles/                  collectstatic output         (STATIC_ROOT)
  * Django's own data files       admin templates/static, form templates, locales
  * PySide6 + QtWebEngine         via PyInstaller's PySide6 hooks
  * WeasyPrint + its data files   UA stylesheets, ICC profile, hyphenation dicts
  * GTK/Pango/HarfBuzz/Fontconfig the native DLLs WeasyPrint dlopen()s
  * packaging/fontconfig          minimal fonts.conf for the bundled fontconfig

NOT bundled on purpose: db.sqlite3 (the development database), tests, the
venv, *.md notes, project_tree.txt. The customer's database lives in
%LOCALAPPDATA%\\140JahanPour (see config/runtime.py), never in the bundle.

WeasyPrint's native libraries are not Python packages, so this spec must be
able to find a GTK/Pango runtime on the BUILD machine. It looks, in order, at
%GTK_BIN_DIR%, %WEASYPRINT_DLL_DIRECTORIES%, C:\\msys64\\mingw64\\bin and
C:\\Program Files\\GTK3-Runtime Win64\\bin, then every folder on PATH. The
build stops with a clear message if they cannot be found -- shipping without
them would build fine but break every PDF print on the customer's PC.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve()  # noqa: F821 - SPECPATH is injected by PyInstaller
APP_NAME = "FuelStation"


def _fail(message):
    raise SystemExit("\n[FuelStation.spec] ERROR: " + message + "\n")


if sys.version_info[:2] != (3, 11):
    print(
        "[FuelStation.spec] WARNING: built with Python %d.%d; the project is "
        "pinned to 3.11.x." % sys.version_info[:2]
    )

# Make `config`, `apps`, `desktop` importable for collect_submodules(), which
# imports packages in an isolated child process, and keep an ambient
# DJANGO_SETTINGS_MODULE from steering PyInstaller's generic Django hook.
sys.path.insert(0, str(ROOT))
os.environ["PYTHONPATH"] = str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")
os.environ.pop("DJANGO_SETTINGS_MODULE", None)

# ---------------------------------------------------------------------------
# Required project resources
# ---------------------------------------------------------------------------
for required in ("templates", "static", "staticfiles"):
    if not (ROOT / required).is_dir():
        _fail(
            "'%s' folder not found next to the spec. For 'staticfiles' run: "
            "py -3.11 manage.py collectstatic --noinput" % required
        )

FONTCONFIG_FILE = ROOT / "packaging" / "fontconfig" / "fonts.conf"
if not FONTCONFIG_FILE.is_file():
    _fail("packaging/fontconfig/fonts.conf is missing.")

# ---------------------------------------------------------------------------
# WeasyPrint native runtime (GTK / Pango / HarfBuzz / Fontconfig) -- Windows
# Names are exactly what weasyprint/text/ffi.py (v69) dlopen()s.
# ---------------------------------------------------------------------------
GTK_REQUIRED_DLLS = [
    "libgobject-2.0-0.dll",
    "libpango-1.0-0.dll",
    "libpangoft2-1.0-0.dll",
    "libharfbuzz-0.dll",
    "libfontconfig-1.dll",
]
GTK_OPTIONAL_DLLS = [
    "libharfbuzz-subset-0.dll",  # WeasyPrint loads it with allow_fail=True
]


def _gtk_candidate_dirs():
    for variable in ("GTK_BIN_DIR", "WEASYPRINT_DLL_DIRECTORIES"):
        for entry in os.environ.get(variable, "").split(";"):
            if entry.strip():
                yield Path(entry.strip())
    yield Path(r"C:\msys64\mingw64\bin")
    yield Path(r"C:\Program Files\GTK3-Runtime Win64\bin")
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry.strip():
            yield Path(entry.strip())


binaries = []

if sys.platform == "win32":
    gtk_dir = None
    for candidate in _gtk_candidate_dirs():
        if (candidate / "libgobject-2.0-0.dll").is_file():
            gtk_dir = candidate
            break
    if gtk_dir is None:
        _fail(
            "GTK/Pango runtime for WeasyPrint not found (libgobject-2.0-0.dll). "
            "Install MSYS2 'mingw-w64-x86_64-pango' or the GTK3 runtime, then set "
            "GTK_BIN_DIR to the folder that contains the DLLs "
            "(e.g. C:\\msys64\\mingw64\\bin) and build again."
        )
    missing = [name for name in GTK_REQUIRED_DLLS if not (gtk_dir / name).is_file()]
    if missing:
        _fail("%s is missing required DLLs: %s" % (gtk_dir, ", ".join(missing)))

    print("[FuelStation.spec] GTK runtime for WeasyPrint: %s" % gtk_dir)

    # 1) Let the build-time child processes that import weasyprint find the DLLs.
    os.environ["WEASYPRINT_DLL_DIRECTORIES"] = str(gtk_dir)
    # 2) Let PyInstaller resolve the DLLs' own dependencies (glib, freetype,
    #    fribidi, ...). Appended, so Python's own DLLs still win on conflicts.
    os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + str(gtk_dir)
    # 3) Ship the top-level libraries at the bundle root (_internal\), next to
    #    where the frozen app loads them from; their dependencies follow.
    for dll in GTK_REQUIRED_DLLS + GTK_OPTIONAL_DLLS:
        if (gtk_dir / dll).is_file():
            binaries.append((str(gtk_dir / dll), "."))
else:
    print(
        "[FuelStation.spec] WARNING: not running on Windows -- the WeasyPrint "
        "GTK/Pango DLLs are NOT bundled. This spec targets Windows builds."
    )

# ---------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------
datas = [
    (str(ROOT / "templates"), "templates"),
    (str(ROOT / "static"), "static"),
    (str(ROOT / "staticfiles"), "staticfiles"),
    (str(FONTCONFIG_FILE), "fontconfig"),
]

for package in (
    "django",       # admin templates/static, django/forms/templates, locale .mo files
    "weasyprint",   # css/html5_ua*.css, html5_ph.css, pdf/sRGB2014.icc
    "pyphen",       # hyphenation dictionaries
    "tinycss2",
    "tinyhtml5",
    "cssselect2",
    "pydyf",
    "fontTools",
    "tzdata",       # Windows has no system tz database; Django uses Asia/Tehran
    "jdatetime",
):
    datas += collect_data_files(package)

# ---------------------------------------------------------------------------
# Hidden imports (things Django/WeasyPrint import by dotted-path string)
# ---------------------------------------------------------------------------


def _not_test_module(name):
    return not any(
        part in ("tests", "test") or part.startswith("test_") for part in name.split(".")
    )


_DJANGO_SKIP = (
    "django.contrib.gis",
    "django.contrib.postgres",
    "django.db.backends.mysql",
    "django.db.backends.oracle",
    "django.db.backends.postgresql",
)

hiddenimports = []

# Project: every app (models, views, migrations, management commands,
# templatetags, context processors, middleware) plus config.* (settings
# modules, urls, wsgi). Test modules are left out.
hiddenimports += collect_submodules("apps", filter=_not_test_module)
hiddenimports += collect_submodules("config", filter=_not_test_module)

# Django loads backends, management commands (migrate, ...), template
# engines/loaders, middleware, context processors, locale formats and
# contrib apps by dotted-path string.
hiddenimports += collect_submodules(
    "django", filter=lambda name: not name.startswith(_DJANGO_SKIP)
)

# WeasyPrint and its pure-Python dependencies; fontTools loads its table
# parsers (ttLib.tables._*) dynamically; woff2 fonts (Vazirmatn) need brotli.
for package in ("weasyprint", "fontTools", "tzdata"):
    hiddenimports += collect_submodules(package)

hiddenimports += [
    "waitress",
    "whitenoise",
    "whitenoise.middleware",
    "jdatetime",
    "sqlite3",
    "cffi",
    "_cffi_backend",
    "pydyf",
    "pyphen",
    "tinycss2",
    "tinyhtml5",
    "cssselect2",
    "brotli",
    "PIL",
    # Qt: the PySide6 hooks collect QtWebEngine's helper process, resources,
    # translations and ICU data once these are seen.
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtPrintSupport",
    "PySide6.QtPdf",              # direct printing (desktop/direct_print.py)
    "desktop.direct_print",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
]

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
a = Analysis(  # noqa: F821
    [str(ROOT / "desktop" / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

# QtWebEngine cannot render anything without its helper process.
_collected = {Path(entry[0]).name.lower() for entry in (a.binaries + a.datas)}
if "qtwebengineprocess.exe" not in _collected and sys.platform == "win32":
    print(
        "[FuelStation.spec] WARNING: QtWebEngineProcess.exe was not collected; "
        "the window will stay blank. Check the PySide6 installation."
    )

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX corrupts Qt/Chromium DLLs and slows start-up
    console=False,  # windowed: no console window for the customer
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
