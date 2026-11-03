"""
Keyboard navigation in EVERY table (templates/partials/_table_row_navigation.html,
included once by base.html): Enter highlights the first row in blue, ArrowDown/
ArrowUp move it, the page scrolls to keep it visible, Enter again exits.

Each table screen is rendered with real data and driven in jsdom by
js_tests/table_navigation.js (skipped when Node or the `jsdom` package is not
installed -- see apps/reports/test_nozzle_ledger_keyboard.py). The expected row
units are computed here, independently of the JavaScript, from the page HTML.
"""

import datetime
import json
import re
import subprocess
import tempfile
import unittest
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

from django.test import TestCase

from apps.core.test_number_display import NumberDisplayFixtureMixin
from apps.deposits.models import Deposit
from apps.inventory.models import TankInventory
from apps.purchases.models import PurchaseInvoice
from apps.reports.test_nozzle_ledger_keyboard import NODE, NODE_ENV
from apps.sales.models import NozzleSale, SalesInvoice
from apps.seals.models import NozzleSeal
from apps.workday.models import DailyWorkingDay

HARNESS = Path(__file__).parent / "js_tests" / "table_navigation.js"


class _TableScan(HTMLParser):
    """Body rows of the tables inside <main>, as lists of (rowspan, colspan) per cell."""

    def __init__(self):
        super().__init__()
        self.main = 0
        self.table = None          # None, or [rows] while inside a navigable table
        self.skip_table = False
        self.in_tbody = False
        self.row = None
        self.tables = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "main":
            self.main += 1
        elif tag == "table" and self.main:
            self.skip_table = a.get("data-row-nav") == "off"
            self.table = [] if not self.skip_table else None
            if self.table is not None:
                self.tables.append(self.table)
        elif tag == "tbody" and self.table is not None:
            self.in_tbody = True
        elif tag == "tr" and self.in_tbody and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.row.append((int(a.get("rowspan", 1)), int(a.get("colspan", 1))))

    def handle_endtag(self, tag):
        if tag == "main":
            self.main -= 1
        elif tag == "table":
            self.table = None
            self.in_tbody = False
        elif tag == "tbody":
            self.in_tbody = False
        elif tag == "tr" and self.row is not None and self.table is not None:
            self.table.append(self.row)
            self.row = None


def expected_groups(html):
    """Rows per navigable unit, in page order (placeholders skipped, rowspans merged)."""
    scan = _TableScan()
    scan.feed(html)
    sizes = []
    for rows in scan.tables:
        remaining = 0
        for cells in rows:
            if len(cells) == 1 and cells[0][1] > 1:            # a single cell spanning the table
                remaining = 0
                continue
            if remaining > 0 and sizes:
                sizes[-1] += 1
                remaining -= 1
                continue
            sizes.append(1)
            remaining = max([c[0] for c in cells] + [1]) - 1
    return sizes


class TableNavigationBase(NumberDisplayFixtureMixin, TestCase):
    def setUp(self):
        self.build_data()
        # More days (so tables are long enough to need scrolling) and a second purchase
        # on some days of the Regular tank (so the ledger has multi-row, rowspan days).
        prev = {self.n1: Decimal("1334572"), self.n2: Decimal("1234.75")}
        for i in range(2, 13):
            wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, i))
            inv = SalesInvoice.objects.create(working_day=wd, operator=self.user)
            for n in (self.n1, self.n2):
                new = prev[n] + Decimal("345.5") * i
                NozzleSale.objects.create(sales_invoice=inv, nozzle=n, previous_meter=prev[n], new_meter=new,
                                          test=Decimal("5"), sales_rate=Decimal("1200"))
                prev[n] = new
            for tank in (self.rtank, self.stank):
                PurchaseInvoice.objects.create(working_day=wd, tank=tank, quantity=12000 * i,
                                               purchase_rate=Decimal("1200"), program_number=f"90{i}", tanker_number=f"A{i}")
                if tank is self.rtank and i % 2 == 0:
                    PurchaseInvoice.objects.create(working_day=wd, tank=tank, quantity=500 * i,
                                                   purchase_rate=Decimal("1200"), program_number=f"91{i}", tanker_number=f"B{i}")
                TankInventory.objects.create(tank=tank, working_day=wd, actual_inventory=Decimal("900000") + i)
        for i, decade in enumerate(("first", "first", "first", "second", "second", "third")):
            Deposit.objects.create(date=datetime.date(2026, 7, 24 + i), year=1405, month=5, decade=decade,
                                   deposit_amount=Decimal("100000") * (i + 1), document_number=f"D{i}")
        for i, section in enumerate(("flag_door_1", "flag_door_2", "pump_door_1", "pump_door_2")):
            NozzleSeal.objects.create(nozzle=self.n1, section=section, date=datetime.date(2026, 8, 1 + i),
                                      seal_number=f"77{i}")

    RANGE = "start_date=2026-07-23&end_date=2026-08-12"

    def pages(self):
        return {
            "فاکتورهای فروش (list)": ("/sales/invoices/", "normal", None),
            "فاکتورهای فروش (day detail)": ("/sales/invoices/2026-08-01/", "normal", None),
            "فاکتورهای خرید (two tables)": (f"/purchases/?{self.RANGE}", "normal", None),
            "واریزی‌ها (month)": ("/deposits/?year=1405&month=5", "normal", None),
            "واریزی‌ها (decade)": ("/deposits/1405/5/first/", "normal", None),
            "پلمپ‌ها": (f"/seals/?{self.RANGE}", "normal", None),
            "دفتر موجودی و عملیات": (f"/reports/petroleum-ledger/?tank_id={self.rtank.id}&{self.RANGE}", "normal", None),
            "گزارش ماهانه مخازن": ("/reports/petroleum-monthly/?year=1405&month=5", "normal", None),
            "گزارش کارکرد هر نازل": (f"/reports/nozzle-ledger/?nozzle_id={self.n2.id}&{self.RANGE}", "nozzle", None),
            "گزارش ماهانه نازل": ("/reports/nozzle-monthly/?year=1405&month=5", "normal", None),
            "لیست اطلاعات فروش": ("/reports/all-nozzles/?year=1405&month=5", "normal", None),
            "صورت وضعیت ماهانه (two tables + inline form)": ("/statement/?year=1405&month=5", "normal", 'input[name="tanker_capacity"]'),
            "مقایسه (two tables)": ("/comparison/?year=1405&month=5", "normal", None),
        }

    def get(self, url):
        resp = self.client.get(url, follow=True)
        self.assertEqual(resp.status_code, 200, url)
        return resp.content.decode()

    def run_harness(self, html, spec):
        self.assertIsNotNone(NODE)
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text(html, encoding="utf-8")
            spec_file = Path(tmp) / "spec.json"
            spec_file.write_text(json.dumps({"file": str(page), **spec}), encoding="utf-8")
            result = subprocess.run([NODE, str(HARNESS), str(spec_file)], env=NODE_ENV,
                                    capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        checks = json.loads(result.stdout)
        failed = [name for name, ok in checks.items() if not ok]
        self.assertEqual(failed, [], f"failed table-navigation checks: {failed}")
        return checks


class TableNavigationStructureTests(TableNavigationBase):
    def test_the_script_is_included_once_on_every_table_page(self):
        for name, (url, _, _) in self.pages().items():
            html = self.get(url)
            self.assertEqual(html.count("window.TableRowNavigation = "), 1, name)
            self.assertIn("tr.row-selected td {", html, name)
            self.assertRegex(html, r"tr\.row-selected td \{[^}]*background: #1d4ed8", name)

    def test_every_table_screen_has_navigable_rows_and_the_ledger_has_multi_row_days(self):
        for name, (url, _, _) in self.pages().items():
            self.assertTrue(expected_groups(self.get(url)), name)
        ledger = expected_groups(self.get(self.pages()["دفتر موجودی و عملیات"][0]))
        self.assertIn(2, ledger)                 # days with two purchase invoices are one unit of two rows
        self.assertEqual(sum(ledger), len(re.findall(r"<tr", self.get(self.pages()["دفتر موجودی و عملیات"][0]).split("<tbody>", 1)[1])))

    def test_two_table_pages_form_one_continuous_list(self):
        html = self.get(self.pages()["فاکتورهای خرید (two tables)"][0])
        scan = _TableScan(); scan.feed(html)
        self.assertEqual(len(scan.tables), 2)
        self.assertEqual(sum(expected_groups(html)), sum(len(t) for t in scan.tables))

    def test_no_per_page_wiring_is_needed(self):
        """Pages without their own init rely on the default (all tables in <main>)."""
        for name in ("فاکتورهای فروش (list)", "واریزی‌ها (month)", "پلمپ‌ها", "دفتر موجودی و عملیات", "مقایسه (two tables)"):
            self.assertNotIn("TableRowNavigation.init", self.get(self.pages()[name][0]).split("window.TableRowNavigation = ", 1)[1].split("</script>", 1)[1], name)

    def test_page_specific_setups_are_kept(self):
        ledger = self.get(self.pages()["گزارش کارکرد هر نازل"][0])
        self.assertIn("onArrowOutsideTableMode", ledger)
        self.assertIn("TableRowNavigation.init", self.get(self.pages()["لیست اطلاعات فروش"][0]))

    def test_viewing_changes_no_stored_data(self):
        before = (NozzleSale.objects.count(), PurchaseInvoice.objects.count(), Deposit.objects.count(),
                  list(TankInventory.objects.values_list("actual_inventory", flat=True).order_by("id")))
        for name, (url, _, _) in self.pages().items():
            self.get(url)
        self.assertEqual(before, (NozzleSale.objects.count(), PurchaseInvoice.objects.count(), Deposit.objects.count(),
                                  list(TankInventory.objects.values_list("actual_inventory", flat=True).order_by("id"))))


@unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
class TableNavigationBehaviourTests(TableNavigationBase):
    def check_page(self, name):
        url, arrows, input_in_table = self.pages()[name]
        html = self.get(url)
        groups = expected_groups(html)
        spec = {"groups": groups, "arrowsOutside": arrows}
        if input_in_table:
            spec["inputInTable"] = input_in_table
        checks = self.run_harness(html, spec)
        self.assertGreaterEqual(len(checks), 20, name)

    def test_sales_invoices_list(self):
        """فاکتورهای فروش: the list of days."""
        self.check_page("فاکتورهای فروش (list)")

    def test_sales_invoice_day_detail(self):
        """فاکتورهای فروش: one day's nozzle rows."""
        self.check_page("فاکتورهای فروش (day detail)")

    def test_purchase_invoices_two_tables(self):
        """فاکتورهای خرید: Regular and Super tables as one continuous list."""
        self.check_page("فاکتورهای خرید (two tables)")

    def test_deposits_month(self):
        """واریزی‌ها: the month's decade totals."""
        self.check_page("واریزی‌ها (month)")

    def test_deposits_decade(self):
        """واریزی‌ها: one decade's deposits."""
        self.check_page("واریزی‌ها (decade)")

    def test_seals(self):
        """پلمپ‌ها."""
        self.check_page("پلمپ‌ها")

    def test_petroleum_ledger_with_multi_row_days(self):
        """دفتر موجودی و عملیات (priority): days with several purchase invoices move as one row."""
        self.check_page("دفتر موجودی و عملیات")

    def test_petroleum_monthly(self):
        """گزارش ماهانه مخازن."""
        self.check_page("گزارش ماهانه مخازن")

    def test_nozzle_ledger_keeps_its_nozzle_mode(self):
        """گزارش کارکرد هر نازل: table mode on Enter, nozzle mode otherwise."""
        self.check_page("گزارش کارکرد هر نازل")

    def test_nozzle_monthly(self):
        """گزارش ماهانه نازل."""
        self.check_page("گزارش ماهانه نازل")

    def test_all_nozzles_list(self):
        """لیست اطلاعات فروش."""
        self.check_page("لیست اطلاعات فروش")

    def test_statement_with_inline_form(self):
        """صورت وضعیت ماهانه: two tables, one with an inline tanker-capacity form."""
        self.check_page("صورت وضعیت ماهانه (two tables + inline form)")

    def test_comparison_two_tables(self):
        """مقایسه سیستم مکانیکی و دیجیتال: mechanical and digital tables."""
        self.check_page("مقایسه (two tables)")

    def test_purchase_page_with_one_empty_table_navigates_only_the_filled_one(self):
        """فاکتورهای خرید where the Super table has no invoices: it shows a message instead of
        a table, so navigation simply covers the Regular table."""
        PurchaseInvoice.objects.filter(tank=self.stank).delete()
        html = self.get(f"/purchases/?{self.RANGE}")
        scan = _TableScan(); scan.feed(html)
        self.assertEqual(len(scan.tables), 1)
        self.run_harness(html, {"groups": expected_groups(html), "arrowsOutside": "normal"})

    def test_placeholder_rows_and_opted_out_tables_are_never_navigated(self):
        """The safeguards: a body row that is one cell spanning the table (a "no data" row) and a
        table marked data-row-nav="off" are skipped. No current screen renders either, so a synthetic
        table is added to a real page and the expectation comes from the independent HTML scan."""
        html = self.get("/deposits/?year=1405&month=5")
        synthetic = (
            '<table id="synthetic"><thead><tr><th>x</th><th>y</th></tr></thead><tbody>'
            "<tr><td>1</td><td>one</td></tr>"
            '<tr><td colspan="2">no data</td></tr>'
            "<tr><td>2</td><td>two</td></tr>"
            '<tr><td colspan="2">no data</td></tr>'
            "</tbody></table>"
            '<table data-row-nav="off"><tbody><tr><td>skip me</td><td>never</td></tr></tbody></table>'
        )
        html = html.replace("</main>", synthetic + "</main>", 1)
        groups = expected_groups(html)
        before = expected_groups(self.get("/deposits/?year=1405&month=5"))
        self.assertEqual(groups, before + [1, 1])             # two real synthetic rows; placeholders/off-table excluded
        checks = self.run_harness(html, {"groups": groups, "arrowsOutside": "normal"})
        self.assertIn("enter: placeholder rows are never selected", checks)

    def test_pages_with_no_rows_are_left_alone(self):
        for url in ("/seals/?start_date=2026-09-20&end_date=2026-09-21",
                    "/purchases/?start_date=2026-09-20&end_date=2026-09-21",
                    f"/reports/petroleum-ledger/?tank_id={self.rtank.id}&start_date=2026-09-20&end_date=2026-09-21"):
            html = self.get(url)
            self.assertEqual(expected_groups(html), [], url)
            self.run_harness(html, {"groups": [], "arrowsOutside": "normal"})
