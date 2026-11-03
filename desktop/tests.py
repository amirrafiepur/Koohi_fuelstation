"""
Phase 10 desktop integration tests that do not require launching Qt.

The actual QWebEngineView startup is intentionally left to a Windows
integration smoke test because CI/test runners may not have Qt WebEngine
or a graphical desktop session.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop import main


class DesktopCommandTests(unittest.TestCase):
    def test_source_server_command_uses_module(self):
        with patch.object(sys, "frozen", False, create=True):
            command = main._server_command(8765)

        self.assertEqual(
            command,
            [sys.executable, "-m", "desktop.main", "--server", "8765"],
        )

    def test_free_port_is_positive(self):
        port = main._find_free_port()
        self.assertGreater(port, 0)

    def test_project_root_exists(self):
        self.assertTrue(Path(main._project_root()).exists())

    def test_environment_uses_desktop_settings(self):
        with patch.dict(os.environ, {}, clear=True):
            main._configure_environment()
            self.assertEqual(
                os.environ["DJANGO_SETTINGS_MODULE"],
                "config.settings.desktop",
            )


class PersistentDataLocationTests(unittest.TestCase):
    """The customer's database must live outside the application files."""

    def test_source_run_uses_development_layout(self):
        from config import runtime

        with patch.object(sys, "frozen", False, create=True), patch.dict(
            os.environ, {}, clear=True
        ):
            self.assertIsNone(runtime.get_app_data_dir())

    def test_frozen_run_uses_local_app_data_folder(self):
        import tempfile
        from config import runtime

        with tempfile.TemporaryDirectory() as tmp:
            local_app_data = Path(tmp) / "Local"
            install_dir = Path(tmp) / "Local" / "Programs" / "140JahanPour"
            install_dir.mkdir(parents=True)
            fake_exe = install_dir / "FuelStation.exe"
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "executable", str(fake_exe)
            ), patch.object(sys, "_MEIPASS", str(install_dir / "_internal"), create=True), patch.dict(
                os.environ, {"LOCALAPPDATA": str(local_app_data)}, clear=True
            ):
                data_dir = runtime.get_app_data_dir()

            self.assertEqual(data_dir, local_app_data / "140JahanPour")
            self.assertTrue(data_dir.is_dir())

    def test_frozen_run_refuses_data_inside_application_files(self):
        import tempfile
        from config import runtime

        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp) / "app"
            install_dir.mkdir()
            fake_exe = install_dir / "FuelStation.exe"
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "executable", str(fake_exe)
            ), patch.object(sys, "_MEIPASS", str(install_dir / "_internal"), create=True), patch.dict(
                os.environ,
                {runtime.DATA_DIR_ENV_VAR: str(install_dir / "data")},
                clear=True,
            ):
                with self.assertRaises(RuntimeError):
                    runtime.get_app_data_dir()

    def test_override_directory_is_honoured(self):
        import tempfile
        from config import runtime

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sys, "frozen", False, create=True), patch.dict(
                os.environ, {runtime.DATA_DIR_ENV_VAR: str(Path(tmp) / "d")}, clear=True
            ):
                self.assertEqual(runtime.get_app_data_dir(), Path(tmp) / "d")


class PreMigrationBackupTests(unittest.TestCase):
    def _make_db(self, path):
        import sqlite3

        connection = sqlite3.connect(str(path))
        connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        connection.execute("INSERT INTO t (v) VALUES ('customer data')")
        connection.commit()
        connection.close()

    def test_backup_is_a_readable_copy(self):
        import sqlite3
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "db.sqlite3"
            self._make_db(db_path)

            backup_path = main._backup_sqlite_file(db_path, Path(tmp) / "backups")

            self.assertTrue(backup_path.is_file())
            self.assertNotEqual(backup_path, db_path)
            connection = sqlite3.connect(str(backup_path))
            try:
                rows = connection.execute("SELECT v FROM t").fetchall()
            finally:
                connection.close()
            self.assertEqual(rows, [("customer data",)])

    def test_old_backups_are_pruned_but_recent_kept(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "db.sqlite3"
            self._make_db(db_path)
            backup_dir = Path(tmp) / "backups"

            for _ in range(5):
                main._backup_sqlite_file(db_path, backup_dir, keep=3)

            self.assertEqual(len(list(backup_dir.glob("db-before-migrate-*.sqlite3"))), 3)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Task 2B: direct printing
# ---------------------------------------------------------------------------

from desktop import direct_print as dp  # noqa: E402


class PrinterChoiceTests(unittest.TestCase):
    def test_virtual_printers_are_recognised(self):
        for name in (
            "Microsoft Print to PDF", "Microsoft XPS Document Writer",
            "OneNote (Desktop)", "Fax", "CutePDF Writer", "Adobe PDF",
        ):
            self.assertTrue(dp.is_virtual_printer(name), name)
        for name in ("HP LaserJet P1102", "Canon LBP6030", "EPSON L3150 Series", "Brother HL-L2320D"):
            self.assertFalse(dp.is_virtual_printer(name), name)

    def test_default_real_printer_is_preferred(self):
        chosen = dp.choose_printer([
            dp.PrinterCandidate("Microsoft Print to PDF", is_default=True),
            dp.PrinterCandidate("Canon LBP6030"),
            dp.PrinterCandidate("HP LaserJet P1102", is_default=True),
        ])
        self.assertEqual(chosen.name, "HP LaserJet P1102")

    def test_first_real_printer_when_default_is_virtual(self):
        chosen = dp.choose_printer([
            dp.PrinterCandidate("Microsoft Print to PDF", is_default=True),
            dp.PrinterCandidate("Canon LBP6030"),
        ])
        self.assertEqual(chosen.name, "Canon LBP6030")

    def test_only_virtual_or_broken_printers_means_no_printer(self):
        self.assertIsNone(dp.choose_printer([]))
        self.assertIsNone(dp.choose_printer([
            dp.PrinterCandidate("Microsoft Print to PDF", is_default=True),
            dp.PrinterCandidate("OneNote"),
            dp.PrinterCandidate("HP LaserJet", has_error=True),
        ]))


class PrintOrFallbackTests(unittest.TestCase):
    """The decision logic, with every side effect replaced by a recorder."""

    def run_case(self, *, printer, send=None, viewer_result=True, detect_raises=False):
        events = []

        def find():
            if detect_raises:
                raise OSError("spooler not running")
            return printer

        def default_send(path, name):
            events.append(("send", Path(path).name, name))

        outcome = dp.print_or_fallback(
            "/tmp/report.pdf",
            open_in_viewer=lambda p: (events.append(("viewer", Path(p).name)), viewer_result)[1],
            show_message=lambda title, text, level: events.append(("message", title, text, level)),
            show_status=lambda text: events.append(("status", text)),
            find_printer_fn=find,
            send_to_printer=send or default_send,
        )
        return outcome, events

    def test_printer_available_prints_silently_without_viewer_or_dialog(self):
        outcome, events = self.run_case(printer=dp.PrinterCandidate("HP LaserJet", True))
        self.assertEqual(outcome.status, "printed")
        self.assertEqual(outcome.printer_name, "HP LaserJet")
        kinds = [e[0] for e in events]
        self.assertEqual(kinds, ["send", "status"])           # no viewer, no blocking message
        self.assertEqual(events[0], ("send", "report.pdf", "HP LaserJet"))
        self.assertIn("HP LaserJet", events[1][1])

    def test_no_printer_shows_persian_message_then_opens_pdf(self):
        outcome, events = self.run_case(printer=None)
        self.assertEqual(outcome.status, "no_printer")
        self.assertEqual([e[0] for e in events], ["message", "viewer"])  # message BEFORE fallback
        _, title, text, level = events[0]
        self.assertEqual(title, dp.MSG_NO_PRINTER_TITLE)
        self.assertIn("چاپگر", text)
        self.assertEqual(level, "info")
        self.assertEqual(events[1], ("viewer", "report.pdf"))

    def test_detection_error_is_treated_as_no_printer(self):
        outcome, events = self.run_case(printer=None, detect_raises=True)
        self.assertEqual(outcome.status, "no_printer")
        self.assertEqual([e[0] for e in events], ["message", "viewer"])

    def test_printing_failure_warns_and_still_delivers_the_pdf(self):
        def boom(path, name):
            raise dp.PrintError("printer offline")

        outcome, events = self.run_case(printer=dp.PrinterCandidate("HP LaserJet"), send=boom)
        self.assertEqual(outcome.status, "failed")
        self.assertIn("printer offline", outcome.detail)
        self.assertEqual([e[0] for e in events], ["message", "viewer"])
        self.assertEqual(events[0][1], dp.MSG_PRINT_FAILED_TITLE)
        self.assertEqual(events[0][3], "warning")

    def test_unexpected_exception_type_is_also_contained(self):
        def boom(path, name):
            raise MemoryError("out of memory while rendering")

        outcome, events = self.run_case(printer=dp.PrinterCandidate("HP LaserJet"), send=boom)
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(events[-1][0], "viewer")

    def test_if_the_viewer_cannot_open_the_operator_is_told_where_the_file_is(self):
        outcome, events = self.run_case(printer=None, viewer_result=False)
        self.assertEqual(outcome.status, "no_printer")
        messages = [e for e in events if e[0] == "message"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[1][1], dp.MSG_VIEWER_FAILED_TITLE)
        self.assertIn("report.pdf", messages[1][2])

    def test_persian_texts_are_present(self):
        for text in (dp.MSG_NO_PRINTER, dp.MSG_PRINT_FAILED, dp.MSG_PRINTED, dp.MSG_PDF_FAILED):
            self.assertTrue(any("\u0600" <= ch <= "\u06ff" for ch in text))


def _qt_available():
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication  # noqa: F401
        from PySide6.QtPdf import QPdfDocument  # noqa: F401
        from PySide6.QtPrintSupport import QPrinter  # noqa: F401
        return True
    except Exception:
        return False


def _make_report_pdf(path, *, landscape, pages):
    """A real WeasyPrint report PDF using the project's print stylesheet."""
    import weasyprint

    rows = "".join(
        f"<tr><td class='numeric'>{i}</td><td class='numeric'>{i * 123456:,}</td></tr>"
        for i in range(1, 36 * pages)
    )
    html = (
        "<!DOCTYPE html><html lang='fa' dir='rtl'><head>"
        "<link rel='stylesheet' href='css/print.css'></head>"
        f"<body class='{'landscape' if landscape else ''}'>"
        "<div class='print-header'><p class='print-header__station-name'>جایگاه</p></div>"
        f"<table class='print-table'><thead><tr><th>ردیف</th><th>مقدار</th></tr></thead><tbody>{rows}</tbody></table>"
        "</body></html>"
    )
    static_dir = Path(main._project_root()) / "static"
    weasyprint.HTML(string=html, base_url=static_dir.as_uri() + "/").write_pdf(str(path))


@unittest.skipUnless(_qt_available(), "PySide6 (QtPdf/QtPrintSupport) not installed")
class QtPrintingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_no_printer_scenario_with_the_real_qt_printer_list(self):
        """Headless machines/CI have no printers: the real detection path
        must report none and the fallback must run end to end."""
        import tempfile
        from PySide6.QtPrintSupport import QPrinterInfo

        real_printers = [
            p.printerName() for p in QPrinterInfo.availablePrinters()
            if not dp.is_virtual_printer(p.printerName())
        ]
        if real_printers:
            self.skipTest("this machine has a real printer installed")

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "r.pdf"
            _make_report_pdf(pdf, landscape=False, pages=1)
            outcome = dp.print_or_fallback(
                pdf,
                open_in_viewer=lambda p: (events.append(("viewer", p.name)), True)[1],
                show_message=lambda t, x, lvl: events.append(("message", t)),
            )
        self.assertEqual(outcome.status, "no_printer")
        self.assertEqual(events, [("message", dp.MSG_NO_PRINTER_TITLE), ("viewer", "r.pdf")])

    def _print_to_file(self, tmp, *, landscape, pages):
        from PySide6.QtPrintSupport import QPrinter

        src = Path(tmp) / "src.pdf"
        out = Path(tmp) / "printed.pdf"
        _make_report_pdf(src, landscape=landscape, pages=pages)

        def factory(name):
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(out))
            return printer

        sent = dp.print_pdf(src, "Fake Printer", printer_factory=factory)
        return src, out, sent

    def test_connected_printer_scenario_portrait_multi_page(self):
        """Render with QtPdf and send to a printer (a PDF-writing QPrinter
        stands in for the paper device): every page arrives, A4 portrait,
        with real ink on it."""
        import tempfile
        import pymupdf

        with tempfile.TemporaryDirectory() as tmp:
            src, out, sent = self._print_to_file(tmp, landscape=False, pages=3)
            source_pages = len(pymupdf.open(str(src)))
            self.assertGreaterEqual(source_pages, 2)
            self.assertEqual(sent, source_pages)
            printed = pymupdf.open(str(out))
            self.assertEqual(len(printed), source_pages)
            rect = printed[0].rect
            self.assertAlmostEqual(rect.width, 595, delta=3)
            self.assertAlmostEqual(rect.height, 842, delta=3)
            pix = printed[0].get_pixmap(dpi=50, colorspace=pymupdf.csGRAY)
            dark = sum(1 for b in pix.samples if b < 128)
            self.assertGreater(dark, 200, "printed page looks blank")

    def test_connected_printer_scenario_landscape(self):
        import tempfile
        import pymupdf

        with tempfile.TemporaryDirectory() as tmp:
            src, out, sent = self._print_to_file(tmp, landscape=True, pages=2)
            printed = pymupdf.open(str(out))
            self.assertEqual(len(printed), sent)
            self.assertAlmostEqual(printed[0].rect.width, 842, delta=3)
            self.assertAlmostEqual(printed[0].rect.height, 595, delta=3)

    def test_unreadable_or_missing_pdf_raises_print_error(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(dp.PrintError):
                dp.print_pdf(Path(tmp) / "missing.pdf", "x", printer_factory=lambda n: None)
            bad = Path(tmp) / "bad.pdf"
            bad.write_bytes(b"not a pdf at all")
            with self.assertRaises(dp.PrintError):
                dp.print_pdf(bad, "x", printer_factory=lambda n: None)

    def test_failed_print_job_still_falls_back_to_the_pdf(self):
        """A printer that is chosen but fails (here: unreadable PDF) must
        end with the PDF opened for the operator, not lost."""
        import tempfile

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.pdf"
            bad.write_bytes(b"%PDF-1.4 truncated")
            outcome = dp.print_or_fallback(
                bad,
                open_in_viewer=lambda p: (events.append("viewer"), True)[1],
                show_message=lambda t, x, lvl: events.append(t),
                find_printer_fn=lambda: dp.PrinterCandidate("Fake Printer", True),
            )
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(events, [dp.MSG_PRINT_FAILED_TITLE, "viewer"])

    def test_persian_message_box_is_right_to_left(self):
        from unittest import mock
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QMessageBox

        seen = {}

        def fake_exec(box):
            seen["text"] = box.text()
            seen["title"] = box.windowTitle()
            seen["direction"] = box.layoutDirection()
            return 0

        with mock.patch.object(QMessageBox, "exec", fake_exec):
            main._show_persian_message(None, dp.MSG_NO_PRINTER_TITLE, dp.MSG_NO_PRINTER, "info")
        self.assertEqual(seen["title"], dp.MSG_NO_PRINTER_TITLE)
        self.assertEqual(seen["text"], dp.MSG_NO_PRINTER)
        self.assertEqual(seen["direction"], Qt.LayoutDirection.RightToLeft)
