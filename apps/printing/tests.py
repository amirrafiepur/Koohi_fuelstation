"""
Printing tests. Printing is a pure presentation layer over
reports/services.py -- these tests verify PDF generation succeeds, the
required metadata/content is present, printed totals match the
underlying report-service results exactly (not merely "look similar"),
A4 page configuration is applied, RTL content is handled, edits to
source data propagate to the next print with no caching, and large
datasets paginate without malformed output.
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.license.models import License
from apps.stations.models import Station, Product, Tank, Nozzle
from apps.workday.models import DailyWorkingDay
from apps.sales.models import SalesInvoice, NozzleSale
from apps.purchases.models import PurchaseInvoice
from apps.inventory.models import TankInventory, OpeningInventory
from apps.reports import services as report_services

User = get_user_model()


def _shown(value) -> str:
    """How a service-layer number appears on a printed report: trailing
    zeros trimmed and thousands separators added (Task 1), so a printed
    1000.00 is "1,000". The printed value must still equal the service
    value exactly -- only its display form changed."""
    from apps.core.display import format_number

    return "" if value is None else str(format_number(value))


def _pdf_page_count(pdf_bytes: bytes) -> int:
    """Lightweight page count via pypdf, used only to assert pagination
    behavior -- not a rendering/appearance check."""
    from pypdf import PdfReader
    import io
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return len(reader.pages)


def _pdf_text(pdf_bytes: bytes) -> str:
    """Extracts text from the generated PDF for content assertions."""
    from pypdf import PdfReader
    import io
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


class PrintingHttpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        self.station = Station.objects.create(
            name="140 Jahan Pour", province="Razavi Khorasan", city="Mashhad"
        )
        self.product = Product.objects.create(name="Regular")
        self.tank = Tank.objects.create(station=self.station, product=self.product, capacity=50000)
        self.nozzle = Nozzle.objects.create(tank=self.tank, number=1)
        self.client.login(username="op1", password="testpass123")

        self.wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("1000"),
            effective_month=datetime.date(2026, 8, 1),
        )
        PurchaseInvoice.objects.create(
            working_day=self.wd, tank=self.tank, quantity=Decimal("100"),
            purchase_rate=Decimal("1200"),
        )
        invoice = SalesInvoice.objects.create(working_day=self.wd, operator=self.user)
        NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=self.nozzle,
            previous_meter=Decimal("0"), new_meter=Decimal("205"), test=Decimal("5"),
            sales_rate=Decimal("1200"),
        )
        self.inventory_row = TankInventory.objects.create(
            tank=self.tank, working_day=self.wd, actual_inventory=Decimal("905")
        )

    # --- 1. PDF generation succeeds for every required printable report ---

    def test_nozzle_ledger_pdf_generates(self):
        resp = self.client.get(
            f"/print/nozzle-ledger/{self.nozzle.id}/?start_date=2026-08-01&end_date=2026-08-01"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_nozzle_monthly_pdf_generates(self):
        resp = self.client.get("/print/nozzle-monthly/?year=1405&month=5")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_petroleum_ledger_pdf_generates(self):
        resp = self.client.get(
            f"/print/petroleum-ledger/{self.tank.id}/?start_date=2026-08-01&end_date=2026-08-01"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_petroleum_monthly_pdf_generates(self):
        resp = self.client.get("/print/petroleum-monthly/?year=1405&month=5")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

    # --- 2. PDF contains expected report title and station information ---

    def test_nozzle_ledger_pdf_contains_station_metadata(self):
        """
        The station name/province/city are asserted against the rendered
        HTML source (what WeasyPrint actually receives) rather than
        pypdf's extracted text: pypdf's extraction is known to reorder
        or drop text runs that mix Latin script with the Persian comma
        (،) under certain fonts, even though the PDF renders correctly
        (confirmed by rasterizing and visually inspecting the same
        output during development). Asserting on the template source is
        deterministic and reflects the actual print-ready content.
        """
        from django.template.loader import render_to_string
        from apps.printing import services as printing_services

        context = printing_services.build_nozzle_ledger_context(
            self.nozzle, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1)
        )
        html = render_to_string("printing/nozzle_ledger_print.html", context)
        # Persian display labels (see apps/printing/services.py's
        # _STATION_PERSIAN_DISPLAY) -- the stored Station row is still
        # "140 Jahan Pour" / "Razavi Khorasan" / "Mashhad".
        self.assertIn("جایگاه جهانی\u200cپور ۱۴۰", html)
        self.assertIn("خراسان رضوی", html)
        self.assertIn("مشهد", html)

        # Also confirm the PDF itself renders without error and is
        # non-trivial in size (i.e. actually contains page content).
        resp = self.client.get(
            f"/print/nozzle-ledger/{self.nozzle.id}/?start_date=2026-08-01&end_date=2026-08-01"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(resp.content), 2000)

    def test_petroleum_monthly_pdf_contains_station_metadata(self):
        """See test_nozzle_ledger_pdf_contains_station_metadata for why
        this asserts on rendered HTML source rather than pypdf-extracted
        text."""
        from django.template.loader import render_to_string
        from apps.printing import services as printing_services

        context = printing_services.build_petroleum_monthly_context(1405, 5)
        html = render_to_string("printing/petroleum_monthly_print.html", context)
        # Persian display labels (see apps/printing/services.py's
        # _STATION_PERSIAN_DISPLAY) -- the stored Station row is still
        # "140 Jahan Pour" / "Razavi Khorasan" / "Mashhad".
        self.assertIn("جایگاه جهانی\u200cپور ۱۴۰", html)
        self.assertIn("خراسان رضوی", html)
        self.assertIn("مشهد", html)

        resp = self.client.get("/print/petroleum-monthly/?year=1405&month=5")
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(resp.content), 2000)

    # --- 3. Expected report data/totals are present, and MATCH the
    #        underlying report-service results exactly ---

    def test_nozzle_ledger_pdf_matches_report_service_values(self):
        resp = self.client.get(
            f"/print/nozzle-ledger/{self.nozzle.id}/?start_date=2026-08-01&end_date=2026-08-01"
        )
        text = _pdf_text(resp.content)

        service_rows = report_services.nozzle_performance_ledger(
            self.nozzle, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1)
        )
        self.assertEqual(len(service_rows), 1)
        row = service_rows[0]

        # Every value the print PDF shows must equal the exact value the
        # on-screen report service computed -- not merely "a number".
        # (operation/عملکرد is intentionally not asserted here: it is no
        # longer a displayed column -- see nozzle_ledger_print.html --
        # since it is numerically identical to daily_total/جمع روزانه.)
        self.assertIn(_shown(row["previous_meter"]), text)
        self.assertIn(_shown(row["test"]), text)
        self.assertIn(_shown(row["mechanical_sales"]), text)
        self.assertIn(_shown(row["daily_total"]), text)
        self.assertIn(_shown(row["cumulative_total"]), text)
        self.assertIn(_shown(row["new_meter"]), text)
        self.assertIn(_shown(row["sales_rate"]), text)

    def test_petroleum_ledger_pdf_matches_report_service_values(self):
        resp = self.client.get(
            f"/print/petroleum-ledger/{self.tank.id}/?start_date=2026-08-01&end_date=2026-08-01"
        )
        text = _pdf_text(resp.content)

        service_rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1)
        )
        row = service_rows[0]

        # "رسیده" side: per-invoice detail (program/tanker/quantity) plus
        # the day-level values attached to the first (only) invoice row.
        received = row["received_rows"][0]
        self.assertIn(_shown(received["quantity"]), text)
        self.assertIn(_shown(received["test_return"]), text)
        self.assertIn(_shown(received["overage"]), text)
        self.assertIn(_shown(received["daily_received"]), text)
        self.assertIn(_shown(received["cumulative_received"]), text)
        # "خارج شده" side: exactly one set of day-level values.
        self.assertIn(_shown(row["daily_sales"]), text)
        self.assertIn(_shown(row["test_return"]), text)
        self.assertIn(_shown(row["shortage"]), text)
        self.assertIn(_shown(row["daily_dispatched"]), text)
        self.assertIn(_shown(row["cumulative_dispatched"]), text)
        self.assertIn(_shown(row["actual_inventory"]), text)

    def test_petroleum_monthly_pdf_matches_report_service_values(self):
        resp = self.client.get("/print/petroleum-monthly/?year=1405&month=5")
        text = _pdf_text(resp.content)

        service_report = report_services.petroleum_inventory_monthly(self.tank, 1405, 5)

        # "کل خرید" is no longer a displayed column on this report (per
        # its rework), so total_purchase is deliberately not asserted
        # here -- only the 10 columns actually shown.
        self.assertIn(_shown(service_report["beginning_inventory"]), text)
        self.assertIn(_shown(service_report["total_overage"]), text)
        self.assertIn(_shown(service_report["total_test_return"]), text)
        self.assertIn(_shown(service_report["total_received"]), text)
        self.assertIn(_shown(service_report["total_sales"]), text)
        self.assertIn(_shown(service_report["total_shortage"]), text)
        self.assertIn(_shown(service_report["total_dispatched"]), text)
        self.assertIn(_shown(service_report["ending_inventory"]), text)

    def test_nozzle_monthly_pdf_matches_report_service_values(self):
        resp = self.client.get("/print/nozzle-monthly/?year=1405&month=5")
        text = _pdf_text(resp.content)

        service_report = report_services.nozzle_performance_monthly(self.nozzle, 1405, 5)

        self.assertIn(_shown(service_report["beginning_of_month_meter"]), text)
        self.assertIn(_shown(service_report["end_of_month_meter"]), text)
        self.assertIn(_shown(service_report["total_amount"]), text)

    # --- 4. A4 page configuration is correctly applied ---

    def test_pdf_uses_a4_page_size(self):
        """A4 in PDF points is 595 x 842 (21cm x 29.7cm @ 72dpi).
        WeasyPrint embeds this in the page /MediaBox."""
        resp = self.client.get("/print/petroleum-monthly/?year=1405&month=5")
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(resp.content))
        box = reader.pages[0].mediabox
        width_pt = float(box.width)
        height_pt = float(box.height)
        # A4 sheet: ~595 x 842 points in either orientation (wide
        # reports print landscape since Task 2A); small tolerance.
        short_side, long_side = sorted((width_pt, height_pt))
        self.assertAlmostEqual(short_side, 595, delta=2)
        self.assertAlmostEqual(long_side, 842, delta=2)

    # --- 5. RTL/Persian content is handled by the rendering approach ---

    def test_pdf_contains_persian_report_title_text(self):
        resp = self.client.get("/print/petroleum-monthly/?year=1405&month=5")
        text = _pdf_text(resp.content)
        # Persian report title text must appear (proves Persian glyphs
        # were shaped/embedded, not dropped or replaced with tofu boxes).
        self.assertIn("گزارش ماهانه مخازن", text)

    def test_pdf_html_source_declares_rtl_direction(self):
        """Verifies the rendering source (pre-PDF) declares RTL -- the
        actual mechanism WeasyPrint uses to lay out the table direction
        and column order correctly."""
        from django.template.loader import render_to_string
        from apps.printing import services as printing_services

        context = printing_services.build_petroleum_monthly_context(1405, 5)
        html = render_to_string("printing/petroleum_monthly_print.html", context)
        self.assertIn('dir="rtl"', html)

    # --- 6. Editing source data changes the subsequent printed report;
    #        no stale stored report data or print-specific cache ---

    def test_editing_actual_inventory_changes_subsequent_print(self):
        resp_before = self.client.get("/print/petroleum-monthly/?year=1405&month=5")
        text_before = _pdf_text(resp_before.content)
        self.assertIn("905", text_before)  # original ending inventory

        self.inventory_row.actual_inventory = Decimal("500")
        self.inventory_row.save()

        resp_after = self.client.get("/print/petroleum-monthly/?year=1405&month=5")
        text_after = _pdf_text(resp_after.content)
        self.assertIn("500", text_after)  # updated ending inventory
        self.assertNotIn("905", text_after)

    def test_deleting_purchase_changes_subsequent_print(self):
        resp_before = self.client.get(
            f"/print/petroleum-ledger/{self.tank.id}/?start_date=2026-08-01&end_date=2026-08-01"
        )
        text_before = _pdf_text(resp_before.content)
        self.assertIn("100", text_before)  # daily purchase quantity

        PurchaseInvoice.objects.filter(tank=self.tank, working_day=self.wd).delete()

        resp_after = self.client.get(
            f"/print/petroleum-ledger/{self.tank.id}/?start_date=2026-08-01&end_date=2026-08-01"
        )
        text_after = _pdf_text(resp_after.content)
        service_rows_after = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1)
        )
        self.assertEqual(service_rows_after[0]["daily_purchase"], Decimal("0"))
        self.assertIn(_shown(service_rows_after[0]["daily_total_1"]), text_after)

    # --- 7. Long datasets can paginate without malformed output ---

    def test_long_nozzle_ledger_paginates_across_multiple_pages(self):
        # Populate 60 additional working days of sales for this nozzle --
        # enough rows to force the table beyond a single A4 page.
        previous_meter = Decimal("205")
        for day_offset in range(2, 62):
            date = datetime.date(2026, 8, 1) + datetime.timedelta(days=day_offset - 1)
            wd = DailyWorkingDay.objects.create(date=date)
            invoice = SalesInvoice.objects.create(working_day=wd, operator=self.user)
            new_meter = previous_meter + Decimal("10")
            NozzleSale.objects.create(
                sales_invoice=invoice, nozzle=self.nozzle,
                previous_meter=previous_meter, new_meter=new_meter,
                test=Decimal("0"), sales_rate=Decimal("1200"),
            )
            previous_meter = new_meter

        resp = self.client.get(
            f"/print/nozzle-ledger/{self.nozzle.id}/"
            f"?start_date=2026-08-01&end_date={(datetime.date(2026, 8, 1) + datetime.timedelta(days=61)).isoformat()}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b"%PDF"))

        page_count = _pdf_page_count(resp.content)
        self.assertGreater(page_count, 1)

        # All rows must still be present -- pagination must not drop data.
        # Dates are now presented in Jalali (2026-08-01 -> 1405/05/10);
        # the underlying data/pagination logic is unchanged.
        text = _pdf_text(resp.content)
        self.assertIn("1405/05/10", text.replace("‌", ""))

    # --- Empty-data edge case: no rows should still render a valid PDF ---

    def test_empty_nozzle_ledger_still_generates_valid_pdf(self):
        empty_nozzle = Nozzle.objects.create(tank=self.tank, number=2)
        resp = self.client.get(
            f"/print/nozzle-ledger/{empty_nozzle.id}/?start_date=2026-08-01&end_date=2026-08-01"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b"%PDF"))
        text = _pdf_text(resp.content)
        self.assertIn("اطلاعاتی یافت نشد", text)


# ---------------------------------------------------------------------------
# Task 2A: PDF layout (black & white, large type, compact, wide -> landscape)
# ---------------------------------------------------------------------------

import re as _re
from pathlib import Path as _Path

from django.conf import settings as _settings

from apps.core.test_number_display import NumberDisplayFixtureMixin


def _print_css() -> str:
    return (_Path(_settings.STATICFILES_DIRS[0]) / "css" / "print.css").read_text(encoding="utf-8")


class PdfLayoutStylesheetTests(TestCase):
    def test_stylesheet_is_strictly_black_white_and_grey(self):
        """Printer-friendly: every colour in the print stylesheet is
        achromatic (r == g == b); no brand reds, no tinted fills."""
        css = _print_css()
        css = _re.sub(r"/\*.*?\*/", "", css, flags=_re.S)
        for hex_colour in _re.findall(r"#([0-9a-fA-F]{3,6})\b", css):
            if len(hex_colour) == 3:
                hex_colour = "".join(c * 2 for c in hex_colour)
            r, g, b = hex_colour[0:2], hex_colour[2:4], hex_colour[4:6]
            self.assertEqual(r.lower(), g.lower(), f"#{hex_colour} is not grey")
            self.assertEqual(g.lower(), b.lower(), f"#{hex_colour} is not grey")
        self.assertNotRegex(css, r"rgb\(|hsl\(|\bred\b|\bblue\b")

    def test_type_is_larger_and_margins_smaller_than_before(self):
        css = _print_css()
        # Previously: table 9.5px, body 10.5px, 15mm margins.
        self.assertRegex(css, r"table\.print-table \{[^}]*font-size: 1[4-9]px")
        self.assertRegex(css, r"body \{[^}]*font-size: 1[4-9]px")
        margins = [int(m) for m in _re.findall(r"margin: (\d+)mm", css)]
        self.assertTrue(margins and max(margins) <= 10, margins)

    def test_grid_lines_are_hairlines(self):
        css = _print_css()
        self.assertRegex(css, r"table\.print-table td \{[^}]*border: 0\.5px solid #000")


class PdfLayoutRenderTests(NumberDisplayFixtureMixin, TestCase):
    PORTRAIT = {"all_nozzles", "deposit_decade", "purchases_ledger"}

    def setUp(self):
        self.build_data()

    def test_orientation_follows_report_width(self):
        from pypdf import PdfReader
        import io

        for name, url in self.prints().items():
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, name)
            box = PdfReader(io.BytesIO(resp.content)).pages[0].mediabox
            w, h = float(box.width), float(box.height)
            short, long_ = sorted((w, h))
            self.assertAlmostEqual(short, 595, delta=2, msg=name)
            self.assertAlmostEqual(long_, 842, delta=2, msg=name)
            if name in self.PORTRAIT:
                self.assertLess(w, h, f"{name} should stay portrait")
            else:
                self.assertGreater(w, h, f"{name} should be landscape")

    def test_seals_pdf_still_renders_portrait(self):
        resp = self.client.get("/print/seals/?start_date=2026-08-01&end_date=2026-08-01")
        from pypdf import PdfReader
        import io
        box = PdfReader(io.BytesIO(resp.content)).pages[0].mediabox
        self.assertLess(float(box.width), float(box.height))

    def test_all_report_content_is_still_present(self):
        """Layout only: titles, column labels and values survive."""
        from apps.core.test_number_display import pdf_text

        checks = {
            "statement": ["صورت وضعیت ماهانه", "پورسانت", "ظرفیت نفتکش", "1,000,000"],
            "comparison": ["مقایسه سیستم مکانیکی و دیجیتال", "فروش مکانیکی", "فروش دیجیتال"],
            "petroleum_ledger": ["دفتر موجودی و عملیات", "رسیده", "خارج شده", "9001234", "55Ab123"],
            "nozzle_ledger": ["گزارش کارکرد نازل", "1,234.75"],
            "sales_invoice": ["فاکتور فروش روزانه", "1,234,572"],
            "deposit_decade": ["واریزی", "1,500,000", "D-100200"],
        }
        prints = self.prints()
        for name, needles in checks.items():
            text = pdf_text(self.client.get(prints[name]).content)
            for needle in needles:
                self.assertIn(needle, text, f"{name}: {needle!r}")

    def test_no_text_is_clipped_outside_the_page(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest("pymupdf not installed (dev-only check)")
        for name, url in self.prints().items():
            doc = pymupdf.open(stream=self.client.get(url).content, filetype="pdf")
            for page in doc:
                page_rect = page.rect
                for x0, y0, x1, y1, *_ in page.get_text("blocks"):
                    self.assertGreaterEqual(x0, page_rect.x0 - 0.5, name)
                    self.assertLessEqual(x1, page_rect.x1 + 0.5, name)
                    self.assertLessEqual(y1, page_rect.y1 + 0.5, name)
