"""
Native desktop entrypoint for the Fuel Station Management App.

Normal mode:
    Starts a local Waitress server as a child process and opens it in a
    PySide6 QWebEngineView window.

Server mode:
    The same executable/interpreter is re-launched with --server and runs
    Waitress only. This keeps the Django server separate from the Qt GUI
    process while still allowing a single executable to be packaged by
    PyInstaller.
"""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
WINDOW_TITLE = "سامانه حسابداری جایگاه ۱۴۰ جهانی پور"


def _project_root() -> Path:
    """Return the source/bundle root used by Django."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[1]

if str(_project_root()) not in sys.path:
    sys.path.insert(0, str(_project_root()))

logger = logging.getLogger("fuelstation") 

# Number of automatic pre-migration database copies that are kept.
BACKUPS_TO_KEEP = 10


def _configure_environment() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.desktop")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")

    # A windowed (console=False) executable has no console, so sys.stdout /
    # sys.stderr are None. Anything that writes to them (Django management
    # commands, print) would then crash.
    for stream_name in ("stdout", "stderr"):
        if getattr(sys, stream_name) is None:
            setattr(sys, stream_name, open(os.devnull, "w", encoding="utf-8"))

    if getattr(sys, "frozen", False):
        bundle_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))

        # WeasyPrint skips its own DLL-directory setup when frozen, and the
        # GTK/Pango DLLs it loads are shipped inside the bundle.
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(bundle_dir))
            except OSError:
                pass

        # Fontconfig (used by Pango) must not look for its configuration at
        # the build machine's install prefix; use the bundled one.
        fontconfig_dir = bundle_dir / "fontconfig"
        fontconfig_file = fontconfig_dir / "fonts.conf"
        if fontconfig_file.is_file():
            os.environ.setdefault("FONTCONFIG_PATH", str(fontconfig_dir))
            os.environ.setdefault("FONTCONFIG_FILE", str(fontconfig_file))


def _backup_sqlite_file(db_path: Path, backup_dir: Path, keep: int = BACKUPS_TO_KEEP) -> Path:
    """
    Make a consistent copy of a SQLite database using SQLite's online backup
    API (safe even if the file is in use), then prune old automatic backups.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"db-before-migrate-{timestamp}.sqlite3"
    counter = 1
    while backup_path.exists():
        backup_path = backup_dir / f"db-before-migrate-{timestamp}-{counter}.sqlite3"
        counter += 1

    source = sqlite3.connect(str(db_path))
    try:
        destination = sqlite3.connect(str(backup_path))
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()

    old_backups = sorted(backup_dir.glob("db-before-migrate-*.sqlite3"))
    for stale in old_backups[:-keep]:
        try:
            stale.unlink()
        except OSError:
            pass

    return backup_path


def _backup_before_migrations() -> None:
    """
    If an EXISTING customer database is about to receive new migrations (i.e.
    the application was just updated), copy it to the backups folder first.

    A fresh installation (no database yet) and a database that is already up
    to date are left alone. If the backup cannot be made, startup is aborted
    rather than migrating customer data without a safety copy.
    """
    from django.conf import settings
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    backup_dir = getattr(settings, "BACKUP_DIR", None)
    if backup_dir is None:
        return  # source/development run

    db_path = Path(settings.DATABASES["default"]["NAME"])
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return  # fresh installation: nothing to protect

    executor = MigrationExecutor(connection)
    pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    connection.close()
    if not pending:
        return

    backup_path = _backup_sqlite_file(db_path, Path(backup_dir))
    logger.info(
        "Database backed up to %s before applying %d migration(s).",
        backup_path,
        len(pending),
    )


def _log_fatal_server_error() -> None:
    """Persist a server start-up failure; a windowed app has no console."""
    try:
        import traceback
        from config.runtime import get_app_data_dir

        data_dir = get_app_data_dir()
        if data_dir is None:
            return
        log_dir = data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "startup-error.log", "a", encoding="utf-8") as handle:
            handle.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            handle.write(traceback.format_exc())
    except Exception:
        pass


def _run_server(port: int) -> int:
    """Run Waitress in the child process."""
    _configure_environment()
    try:
        return _serve_django(port)
    except BaseException:
        _log_fatal_server_error()
        raise


def _serve_django(port: int) -> int:
    # Import Django/Waitress only in server mode so the GUI process does not
    # carry Django server startup imports unnecessarily.
    import django
    from waitress import serve

    django.setup()

    # A packaged installation has its mutable SQLite database under
    # LocalAppData (see config/runtime.py), never inside the application
    # files, so replacing the application with a newer version keeps the
    # customer's data. Run migrations automatically on startup so a fresh
    # installation -- or an updated one -- is structurally ready before the
    # GUI opens; an existing database is copied to the backups folder first
    # if it is about to receive new migrations. The fixed station/nozzle
    # configuration is safe to seed idempotently (get_or_create only; it
    # never overwrites existing values). We do NOT silently create a license
    # or operator account because those are business/security decisions
    # outside the approved architecture.
    from django.core.management import call_command

    _backup_before_migrations()
    call_command("migrate", interactive=False, verbosity=0)
    call_command("seed_station", verbosity=0)

    from config.wsgi import application

    print(f"Fuel Station server listening on http://{HOST}:{port}", flush=True)
    serve(application, host=HOST, port=port, threads=4)
    return 0


def _find_free_port() -> int:
    """Ask Windows for an unused localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _server_command(port: int) -> list[str]:
    """
    Build the child-process command.

    In a PyInstaller build, sys.executable is the packaged application and
    --server switches that executable into server mode. In source mode,
    python -m desktop.main does the same thing.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--server", str(port)]
    return [sys.executable, "-m", "desktop.main", "--server", str(port)]


def _start_server(port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = "config.settings.desktop"

    creationflags = 0
    startupinfo = None

    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    return subprocess.Popen(
        _server_command(port),
        cwd=str(_project_root()),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        startupinfo=startupinfo,
    )


def _wait_for_server(port: int, process: subprocess.Popen, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False

        try:
            with socket.create_connection((HOST, port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.1)

    return False


def _stop_server(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _make_print_download_dir() -> Path:
    """
    Temporary directory for PDFs generated by the print/چاپ links.

    QWebEngineView's built-in PDF viewer is not reliable for the inline
    (Content-Disposition: inline) PDF responses this app's print views
    return -- the navigation reports success but the embedded PDF plugin
    can be left showing nothing. Routing print downloads through
    QWebEngineProfile.downloadRequested and opening the saved file with
    the OS's own PDF handler (QDesktopServices.openUrl) sidesteps that
    unreliable in-view PDF rendering entirely and is registered for
    cleanup on interpreter exit.
    """
    directory = Path(tempfile.mkdtemp(prefix="fuelstation-print-"))
    atexit.register(shutil.rmtree, directory, ignore_errors=True)
    return directory


def _show_persian_message(parent, title: str, text: str, level: str = "info") -> None:
    """Blocking, right-to-left Persian message box for the print workflow."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    from desktop import direct_print

    box = QMessageBox(parent)
    box.setIcon(
        QMessageBox.Icon.Warning if level == "warning" else QMessageBox.Icon.Information
    )
    box.setWindowTitle(title)
    box.setText(text)
    box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    ok_button = box.addButton(direct_print.MSG_BUTTON_OK, QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(ok_button)
    box.exec()


def _print_saved_pdf(direct_print, saved_path: Path, open_in_viewer, show_message, show_status):
    """Run direct_print.print_or_fallback with a busy cursor while the
    pages are rendered and spooled."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    def message_with_normal_cursor(*args) -> None:
        # A message box must not show the busy cursor.
        QApplication.restoreOverrideCursor()
        try:
            show_message(*args)
        finally:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        return direct_print.print_or_fallback(
            saved_path,
            open_in_viewer=open_in_viewer,
            show_message=message_with_normal_cursor,
            show_status=show_status,
        )
    finally:
        QApplication.restoreOverrideCursor()


def _connect_print_download_handler(view, download_dir: Path) -> None:
    """
    Save any PDF the WebEngine profile tries to download to a private temp
    directory and hand it to the OS's default PDF viewer, instead of
    letting QWebEngineView attempt (and unreliably fail at) showing it
    inline. Non-PDF downloads are declined -- this app has no other
    intentional download links, and silently accepting arbitrary
    downloads is not part of the approved print workflow.

    A print link is a target="_blank" navigation that this app's
    SameWindowPage redirects onto the same page (see _run_gui). Qt still
    runs that redirected navigation through its normal load sequence
    before downloadRequested fires, and that in-flight navigation clears
    the current document -- QUrl.toString() keeps reporting the report
    page's address, but the rendered DOM underneath it is emptied out.
    view.reload() cannot fix this: Qt's "current entry" to reload is the
    print URL itself (the navigation that was in flight when the download
    took over), not the report page, so reloading only re-triggers the
    same download in a loop. What is reliable is the page's own
    urlChanged signal: it fires for every *committed* navigation, and a
    redirected-to-download print link never actually commits one (its
    load reports ok=False), so the last URL that signal ever reports is
    genuinely the last real page the operator was looking at. Recording
    that and navigating back to it once the download settles restores
    the exact page the operator was on, driven by the download's own
    finished-state signal rather than a fixed delay.
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWebEngineCore import QWebEngineDownloadRequest

    from desktop import direct_print

    last_page_url = {"value": view.url()}

    def open_in_viewer(path: Path) -> bool:
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def show_message(title: str, text: str, level: str) -> None:
        _show_persian_message(view, title, text, level)

    def show_status(text: str) -> None:
        window = view.window()
        status_bar = getattr(window, "statusBar", None)
        if callable(status_bar):
            status_bar().showMessage(text, 6000)

    def on_url_changed(url: "QUrl") -> None:
        last_page_url["value"] = url

    view.urlChanged.connect(on_url_changed)

    profile = view.page().profile()

    def on_download_requested(download: "QWebEngineDownloadRequest") -> None:
        is_pdf = (download.mimeType() or "").lower() == "application/pdf"
        suggested_name = download.suggestedFileName() or "report.pdf"
        if not is_pdf and not suggested_name.lower().endswith(".pdf"):
            download.cancel()
            return

        download.setDownloadDirectory(str(download_dir))
        download.setDownloadFileName(suggested_name)
        return_url = last_page_url["value"]

        settled_states = (
            QWebEngineDownloadRequest.DownloadState.DownloadCompleted,
            QWebEngineDownloadRequest.DownloadState.DownloadInterrupted,
            QWebEngineDownloadRequest.DownloadState.DownloadCancelled,
        )

        def on_state_changed(state) -> None:
            if state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
                # Send the report straight to the connected printer; with
                # no printer (or if printing fails) the operator is told in
                # Persian and the PDF opens in the OS viewer as before, so
                # the document is never lost. See desktop/direct_print.py.
                saved_path = download_dir / suggested_name
                _print_saved_pdf(
                    direct_print, saved_path, open_in_viewer, show_message, show_status
                )
            elif state == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
                show_message(
                    direct_print.MSG_PDF_FAILED_TITLE,
                    direct_print.MSG_PDF_FAILED,
                    "warning",
                )
            if state in settled_states and return_url.isValid():
                view.setUrl(return_url)

        download.stateChanged.connect(on_state_changed)
        download.accept()

    profile.downloadRequested.connect(on_download_requested)


def _run_gui(port: int) -> int:
    # Qt imports stay out of server mode.
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication, QMainWindow
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWebEngineWidgets import QWebEngineView

    server = _start_server(port)
    if not _wait_for_server(port, server):
        _stop_server(server)
        raise RuntimeError(
            "Django/Waitress could not be started on localhost. "
            "Run the application from a terminal once to inspect the "
            "startup error if this persists."
        )

    class MainWindow(QMainWindow):
        def closeEvent(self, event):  # noqa: N802 - Qt API name
            _stop_server(server)
            event.accept()

    class SameWindowPage(QWebEnginePage):
        """
        The report print links use target="_blank" so they still work if
        this app is ever opened in a real browser. Inside QWebEngineView,
        an un-handled target="_blank" tries to open a brand-new window via
        createWindow(); with nothing to handle that new window, Qt silently
        drops the whole navigation and downloadRequested is never even
        reached. Returning this same page keeps the navigation (and the
        PDF download it triggers) on the one window this app has.
        """

        def createWindow(self, _window_type):  # noqa: N802 - Qt API name
            return self

    app = QApplication(sys.argv)
    app.setApplicationName(WINDOW_TITLE)
    app.setOrganizationName("140 Jahan Pour")

    window = MainWindow()
    window.setWindowTitle(WINDOW_TITLE)
    window.resize(1200, 760)
    window.setMinimumSize(900, 600)

    view = QWebEngineView()
    view.setPage(SameWindowPage(view))

    print_download_dir = _make_print_download_dir()
    _connect_print_download_handler(view, print_download_dir)

    view.setUrl(QUrl(f"http://{HOST}:{port}/"))
    window.setCentralWidget(view)
    window.show()

    return app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--server", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("_server_port", nargs="?", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.server:
        port = args.port or args._server_port or DEFAULT_PORT
        return _run_server(port)

    port = args.port or _find_free_port()
    return _run_gui(port)


if __name__ == "__main__":
    raise SystemExit(main())
