"""
"لیست اطلاعات فروش": the monthly, nozzle-based report, one FUEL TYPE at a time
(screen + PDF + keyboard).

  Regular (بنزین معمولی): nozzles 1-18, 25, 26  (20 rows)
  Super   (بنزین سوپر)  : nozzles 19-24         (6 rows)
Regular and Super nozzles are never mixed; the summary strip, the table and the
PDF all follow the selected fuel. The nozzle sets come from the seeded station
(seed_station), i.e. from the data model.

Expected figures are worked BY HAND from the raw meter readings, tests and frozen
rates (operation = new - previous; mechanical sales = operation - test; amount =
mechanical sales x rate), then compared with the service, the page and the PDF.

JALALI 1405/05 (2026-07-23 .. 2026-08-22):
  nozzle 1  (Regular): d1 0->1000 test10 @1200 | d2 1000->2500 test5 @1300
              operation 2,500  test 15  sales 2,485  amount 1,188,000+1,943,500 = 3,131,500
  nozzle 2  (Regular): d1 500->900 test0 @1200      -> 400 | 0 | 400 | 480,000
  nozzle 26 (Regular): d2 100->160 test4 @1500      -> 60 | 4 | 56 | 84,000
  nozzle 19 (Super)  : d1 0->300 test2 @1500 | d3 300->450 test0 @1600
              operation 450  test 2  sales 448  amount 447,000+240,000 = 687,000
  REGULAR TOTALS: operation 2,960 | test 19 | sales 2,941 | amount 3,695,500
  SUPER   TOTALS: operation   450 | test  2 | sales   448 | amount   687,000
  (together: 3,410 | 21 | 3,389 | 4,382,500 -- the old all-26-nozzle totals)
JALALI 1405/06 (must never leak into 05): nozzle 1 2500->2800 test1 @1300 -> 300 | 1 | 299 | 388,700
"""

import datetime
import io
import json
import re
import subprocess
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.core.test_number_display import pdf_text, render_pdf_with_html
from apps.license.models import License
from apps.reports import services as report_services
from apps.reports.test_nozzle_ledger_keyboard import NODE, NODE_ENV
from apps.sales.models import NozzleSale, SalesInvoice
from apps.stations.models import Nozzle, Tank
from apps.workday.models import DailyWorkingDay

User = get_user_model()
HARNESS = Path(__file__).parent / "js_tests" / "all_nozzles_keyboard.js"
D = Decimal

REGULAR_NUMBERS = list(range(1, 19)) + [25, 26]
SUPER_NUMBERS = list(range(19, 25))
NUMBERS = {"Regular": REGULAR_NUMBERS, "Super": SUPER_NUMBERS}
LABEL = {"Regular": "بنزین معمولی", "Super": "بنزین سوپر"}

# nozzle -> (operation, test, mechanical sales, amount)
DATA_05 = {1: (2500, 15, 2485, 3131500), 2: (400, 0, 400, 480000), 26: (60, 4, 56, 84000), 19: (450, 2, 448, 687000)}
DATA_06 = {1: (300, 1, 299, 388700)}
FIRST_LAST_05 = {1: (0, 2500), 2: (500, 900), 26: (100, 160), 19: (0, 450)}      # (first previous, last new)
FIRST_LAST_06 = {1: (2500, 2800)}
TOTALS_05 = {"Regular": (2960, 19, 2941, 3695500), "Super": (450, 2, 448, 687000)}
TOTALS_06 = {"Regular": (300, 1, 299, 388700), "Super": (0, 0, 0, 0)}
OLD_ALL_26_TOTALS_05 = (3410, 21, 3389, 4382500)

FIELDS = ("total_operation", "total_test", "total_mechanical_sales", "total_amount")
TOTAL_KEYS = ("operation", "test", "mechanical-sales", "amount")


def fmt(n):
    return f"{n:,}"


def expected_row(number, month_data, first_last):
    """The six cells a nozzle's row must show: number | first | last | sales | test | operation."""
    op, test, sales, _amount = month_data.get(number, (0, 0, 0, 0))
    first, last = first_last.get(number, (None, None))
    dash = "—"
    return [str(number), dash if first is None else fmt(first), dash if last is None else fmt(last),
            fmt(sales), fmt(test), fmt(op)]


def screen_totals(html):
    d = dict(re.findall(r'data-total="([a-z-]+)"[^>]*>([^<]*)<', html))
    return tuple(d[k] for k in TOTAL_KEYS)


def table_rows(html, table_id="all-nozzles-table"):
    body = html.split(f'id="{table_id}"', 1)[1].split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return [[c.strip() for c in re.findall(r"<td[^>]*>([^<]*)</td>", tr)]
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, flags=re.S)]


def to_int(text):
    return int(text.replace(",", ""))


def pdf_summary(html):
    block = html.split("print-summary", 1)[1].split("</table>", 1)[0]
    return tuple(v.strip() for v in re.findall(r'class="numeric"[^>]*>([^<]*)<', block))


def pdf_table_rows(html):
    main = html.split("print-summary", 1)[1].split("</table>", 1)[1]
    body = main.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return [[c.strip() for c in re.findall(r"<td[^>]*>([^<]*)</td>", tr)]
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, flags=re.S)]


class AllNozzlesBase(TestCase):
    def add_sale(self, day, number, prev, new, test=0, rate=1200):
        wd, _ = DailyWorkingDay.objects.get_or_create(date=day)
        inv, _ = SalesInvoice.objects.get_or_create(working_day=wd, defaults={"operator": self.user})
        return NozzleSale.objects.create(sales_invoice=inv, nozzle=Nozzle.objects.get(number=number),
                                         previous_meter=D(prev), new_meter=D(new), test=D(test), sales_rate=D(rate))

    def setUp(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 7, 23), duration_days=365)
        call_command("seed_station", stdout=io.StringIO())             # the real station: 2 tanks, 26 nozzles
        self.tank = {"Regular": Tank.objects.get(product__name="Regular"),
                     "Super": Tank.objects.get(product__name="Super")}
        self.client.login(username="op1", password="testpass123")
        day = datetime.date
        self.add_sale(day(2026, 7, 24), 1, 0, 1000, 10, 1200)
        self.add_sale(day(2026, 7, 26), 1, 1000, 2500, 5, 1300)
        self.add_sale(day(2026, 7, 24), 2, 500, 900, 0, 1200)
        self.add_sale(day(2026, 7, 24), 19, 0, 300, 2, 1500)
        self.add_sale(day(2026, 8, 2), 19, 300, 450, 0, 1600)
        self.add_sale(day(2026, 7, 26), 26, 100, 160, 4, 1500)
        self.add_sale(day(2026, 8, 25), 1, 2500, 2800, 1, 1300)      # month 06 -- must not leak into 05

    def tid(self, fuel):
        return self.tank[fuel].id

    def url(self, month=5, fuel="Regular", year=1405):
        return f"/reports/all-nozzles/?year={year}&month={month}&tank_id={self.tid(fuel)}"

    def print_url(self, month=5, fuel="Regular", year=1405):
        return f"/print/all-nozzles/?year={year}&month={month}&tank_id={self.tid(fuel)}"

    def page(self, month=5, fuel="Regular", year=1405):
        resp = self.client.get(self.url(month, fuel, year))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()


class SeedSanityTests(AllNozzlesBase):
    def test_the_seeded_station_has_the_expected_nozzle_sets(self):
        for fuel in ("Regular", "Super"):
            self.assertEqual(sorted(Nozzle.objects.filter(tank=self.tank[fuel]).values_list("number", flat=True)),
                             NUMBERS[fuel])
        self.assertEqual((len(REGULAR_NUMBERS), len(SUPER_NUMBERS)), (20, 6))


class ServiceTests(AllNozzlesBase):
    def rows(self, month, fuel):
        return report_services.all_nozzles_monthly_summary(1405, month, self.tank[fuel])

    def test_each_fuel_lists_exactly_its_own_nozzles_in_order(self):
        for fuel in ("Regular", "Super"):
            self.assertEqual([r["nozzle_number"] for r in self.rows(5, fuel)], NUMBERS[fuel], fuel)

    def test_regular_and_super_are_never_mixed(self):
        regular = {r["nozzle_number"] for r in self.rows(5, "Regular")}
        sup = {r["nozzle_number"] for r in self.rows(5, "Super")}
        self.assertEqual(regular & sup, set())
        self.assertEqual(regular | sup, set(range(1, 27)))
        self.assertTrue(sup.isdisjoint({1, 2, 18, 25, 26}) and regular.isdisjoint(range(19, 25)))

    def test_each_row_equals_the_hand_worked_monthly_figures(self):
        for month, data, first_last in ((5, DATA_05, FIRST_LAST_05), (6, DATA_06, FIRST_LAST_06)):
            for fuel in ("Regular", "Super"):
                for r in self.rows(month, fuel):
                    op, test, sales, amount = data.get(r["nozzle_number"], (0, 0, 0, 0))
                    self.assertEqual(tuple(r[f] for f in FIELDS), (D(op), D(test), D(sales), D(amount)), (month, fuel, r["nozzle_number"]))
                    first, last = first_last.get(r["nozzle_number"], (None, None))
                    self.assertEqual(r["first_meter"], None if first is None else D(first))
                    self.assertEqual(r["last_meter"], None if last is None else D(last))

    def test_summary_totals_per_fuel_equal_hand_sums_and_column_sums(self):
        for month, expected in ((5, TOTALS_05), (6, TOTALS_06)):
            for fuel in ("Regular", "Super"):
                rows = self.rows(month, fuel)
                totals = report_services.all_nozzles_monthly_totals(rows)
                self.assertEqual(tuple(totals[f] for f in FIELDS), tuple(D(x) for x in expected[fuel]), (month, fuel))
                for f in FIELDS:
                    self.assertEqual(totals[f], sum(r[f] for r in rows))

    def test_the_two_fuels_add_up_to_the_old_all_nozzle_totals(self):
        both = [report_services.all_nozzles_monthly_totals(self.rows(5, f)) for f in ("Regular", "Super")]
        self.assertEqual(tuple(sum(t[f] for t in both) for f in FIELDS), tuple(D(x) for x in OLD_ALL_26_TOTALS_05))

    def test_other_months_never_leak_in(self):
        regular_06 = {r["nozzle_number"]: r for r in self.rows(6, "Regular")}
        self.assertEqual(regular_06[1]["total_operation"], D(300))
        self.assertEqual(regular_06[26]["total_operation"], D(0))
        self.assertEqual(report_services.all_nozzles_monthly_totals(self.rows(9, "Super"))["total_amount"], D(0))

    def test_a_month_with_no_sales_still_lists_the_fuels_nozzles(self):
        self.assertEqual(len(self.rows(9, "Regular")), 20)
        self.assertEqual(len(self.rows(9, "Super")), 6)


class SelectorAndScreenTests(AllNozzlesBase):
    def test_default_is_regular_petrol(self):
        html = self.client.get("/reports/all-nozzles/?year=1405&month=5").content.decode()
        self.assertEqual([r[0] for r in table_rows(html)], [str(n) for n in REGULAR_NUMBERS])
        self.assertRegex(html, rf'<option value="{self.tid("Regular")}" selected>')

    def test_fuel_selector_offers_both_fuels_and_shows_the_selected_one(self):
        for fuel in ("Regular", "Super"):
            html = self.page(5, fuel)
            select = html.split('id="fuel-select"', 1)[1].split("</select>", 1)[0]
            options = re.findall(r'<option value="(\d+)"([^>]*)>([^<]*)</option>', select)
            self.assertEqual([(o[0], o[2]) for o in options],
                             [(str(self.tid("Regular")), "بنزین معمولی"), (str(self.tid("Super")), "بنزین سوپر")])
            selected = [o for o in options if "selected" in o[1]]
            self.assertEqual([s[2] for s in selected], [LABEL[fuel]])
            self.assertIn("نوع سوخت", html)

    def test_each_fuel_shows_only_its_nozzles_and_never_the_other_fuels(self):
        for fuel, other in (("Regular", "Super"), ("Super", "Regular")):
            rows = table_rows(self.page(5, fuel))
            numbers = [int(r[0]) for r in rows]
            self.assertEqual(numbers, NUMBERS[fuel])
            self.assertEqual(len(rows), len(NUMBERS[fuel]))
            self.assertTrue(set(numbers).isdisjoint(NUMBERS[other]))
            self.assertLess(len(rows), 26)                                   # the all-26 view no longer exists

    def test_rows_carry_the_hand_worked_values(self):
        for fuel in ("Regular", "Super"):
            for r in table_rows(self.page(5, fuel)):
                self.assertEqual(r, expected_row(int(r[0]), DATA_05, FIRST_LAST_05), (fuel, r[0]))

    def test_header_labels_and_summary_labels_are_unchanged(self):
        html = self.page(5, "Super")
        head = html.split('id="all-nozzles-table"', 1)[1].split("</thead>", 1)[0]
        self.assertEqual(re.findall(r"<th[^>]*>([^<]*)</th>", head),
                         ["شماره نازل", "کنتور اول ماه", "کنتور آخر ماه", "جمع فروش مکانیکی", "جمع آزمایش", "جمع کارکرد"])
        summary = html.split('id="all-nozzles-totals"', 1)[1].split("</div>\n  </div>", 1)[0]
        self.assertEqual(re.findall(r'<div class="form-label">([^<]+)</div>', summary),
                         ["جمع کارکرد", "مجموع آزمایش", "مجموع فروش مکانیکی", "مجموع مبلغ کل"])

    def test_summary_follows_the_selected_fuel(self):
        for month, expected in ((5, TOTALS_05), (6, TOTALS_06)):
            for fuel in ("Regular", "Super"):
                self.assertEqual(screen_totals(self.page(month, fuel)), tuple(fmt(x) for x in expected[fuel]), (month, fuel))

    def test_summary_equals_the_sums_of_the_displayed_rows(self):
        for fuel in ("Regular", "Super"):
            html = self.page(5, fuel)
            rows = table_rows(html)
            shown = tuple(to_int(x) for x in screen_totals(html))
            self.assertEqual(shown[:3], (sum(to_int(r[5]) for r in rows), sum(to_int(r[4]) for r in rows),
                                         sum(to_int(r[3]) for r in rows)))
            self.assertEqual(shown[3], TOTALS_05[fuel][3])

    def test_summary_sits_above_the_table(self):
        html = self.page(5, "Super")
        self.assertLess(html.index('id="all-nozzles-totals"'), html.index('id="all-nozzles-table"'))

    def test_month_and_year_changes_keep_the_selected_fuel(self):
        html = self.page(6, "Super")
        self.assertEqual(screen_totals(html), ("0", "0", "0", "0"))
        self.assertEqual(len(table_rows(html)), 6)
        tid = self.tid("Super")
        self.assertIn(f"&month=' + this.value + '&tank_id={tid}'", html)                 # month selector
        self.assertIn(f"this.value + '&month=6&tank_id={tid}'", html)                    # year input
        self.assertIn(f"/print/all-nozzles/?year=1405&month=6&tank_id={tid}", html)      # print link
        self.assertIn("year=1405&month=6&tank_id=' + this.value", html)                  # fuel selector keeps the month

    def test_unknown_tank_is_a_404_and_other_pages_unaffected(self):
        self.assertEqual(self.client.get("/reports/all-nozzles/?year=1405&month=5&tank_id=99999").status_code, 404)
        self.assertEqual(self.client.get("/print/all-nozzles/?year=1405&month=5&tank_id=99999").status_code, 404)
        nozzle = Nozzle.objects.get(number=1)
        resp = self.client.get(f"/reports/nozzle-ledger/?nozzle_id={nozzle.id}&start_date=2026-07-23&end_date=2026-08-22")
        self.assertEqual(resp.status_code, 200)

    def test_viewing_changes_no_stored_data(self):
        before = list(NozzleSale.objects.values_list("id", "previous_meter", "new_meter", "test", "sales_rate").order_by("id"))
        for fuel in ("Regular", "Super"):
            self.page(5, fuel)
            self.client.get(self.print_url(5, fuel))
        self.assertEqual(before, list(NozzleSale.objects.values_list(
            "id", "previous_meter", "new_meter", "test", "sales_rate").order_by("id")))


class PdfTests(AllNozzlesBase):
    def test_pdf_rows_and_summary_match_the_screen_for_both_fuels(self):
        for month in (5, 6, 9):
            for fuel in ("Regular", "Super"):
                screen = self.page(month, fuel)
                resp, html = render_pdf_with_html(self.client, self.print_url(month, fuel))
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.content.startswith(b"%PDF"))
                self.assertEqual(pdf_table_rows(html), table_rows(screen), (month, fuel))
                self.assertEqual(pdf_summary(html), screen_totals(screen), (month, fuel))

    def test_pdf_contains_only_the_selected_fuels_nozzles(self):
        for fuel in ("Regular", "Super"):
            _, html = render_pdf_with_html(self.client, self.print_url(5, fuel))
            self.assertEqual([int(r[0]) for r in pdf_table_rows(html)], NUMBERS[fuel])

    def test_pdf_values_and_totals_are_the_hand_worked_ones(self):
        for fuel in ("Regular", "Super"):
            _, html = render_pdf_with_html(self.client, self.print_url(5, fuel))
            self.assertEqual(pdf_summary(html), tuple(fmt(x) for x in TOTALS_05[fuel]))
            for r in pdf_table_rows(html):
                self.assertEqual(r, expected_row(int(r[0]), DATA_05, FIRST_LAST_05))

    def test_pdf_says_which_fuel_and_keeps_the_headings(self):
        for fuel in ("Regular", "Super"):
            resp, html = render_pdf_with_html(self.client, self.print_url(5, fuel))
            self.assertIn(f"{LABEL[fuel]} — سال 1405 — ماه 5", html)
            other = LABEL["Super" if fuel == "Regular" else "Regular"]
            self.assertNotIn(other, html.split("<table", 1)[0])                # the header names only this fuel
            for needle in ("کارکرد تمام نازل‌ها", "جایگاه", "شماره نازل", "کنتور اول ماه", "کنتور آخر ماه", "جمع فروش مکانیکی",
                           "جمع آزمایش", "جمع کارکرد", "مجموع آزمایش", "مجموع فروش مکانیکی", "مجموع مبلغ کل"):
                self.assertIn(needle, html, needle)
            main = html.split("print-summary", 1)[1].split("</table>", 1)[1]
            self.assertNotIn("جمع مبلغ کل", main)
            self.assertIn("مجموع مبلغ کل", html.split("</table>", 1)[0])
            self.assertLess(html.index("print-summary"), html.index("شماره نازل"))
            self.assertIn(fmt(TOTALS_05[fuel][3]), pdf_text(resp.content))

    def test_default_without_tank_is_regular_and_filename_names_the_fuel(self):
        resp = self.client.get("/print/all-nozzles/?year=1405&month=5")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("regular", resp["Content-Disposition"].lower())
        sup = self.client.get(self.print_url(5, "Super"))
        self.assertIn("super", sup["Content-Disposition"].lower())

    def test_each_pdf_is_one_portrait_page_with_unchanged_type_size(self):
        from pypdf import PdfReader
        for fuel in ("Regular", "Super"):
            data = self.client.get(self.print_url(5, fuel)).content
            reader = PdfReader(io.BytesIO(data))
            self.assertEqual(len(reader.pages), 1, fuel)
            self.assertLess(float(reader.pages[0].mediabox.width), float(reader.pages[0].mediabox.height))
            try:
                import pymupdf
            except ImportError:
                continue
            doc = pymupdf.open(stream=data, filetype="pdf")
            sizes = [span["size"] for block in doc[0].get_text("dict")["blocks"] if "lines" in block
                     for line in block["lines"] for span in line["spans"]
                     if re.fullmatch(r"[\d,]+", span["text"].strip()) and len(span["text"].strip()) >= 3]
            self.assertTrue(sizes)
            self.assertGreaterEqual(min(sizes), 10.4)                      # 14px == 10.5pt, as before


class KeyboardTests(AllNozzlesBase):
    def test_both_fuel_pages_use_the_shared_row_navigation(self):
        for fuel in ("Regular", "Super"):
            html = self.page(5, fuel)
            self.assertIn('class="row-nav-table"', html)
            self.assertIn("TableRowNavigation.init", html)
            self.assertIn("#all-nozzles-table tbody tr", html)

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_keyboard_navigation_on_both_fuels(self):
        for fuel in ("Regular", "Super"):
            with tempfile.TemporaryDirectory() as tmp:
                page = Path(tmp) / "page.html"
                page.write_text(self.page(5, fuel), encoding="utf-8")
                result = subprocess.run([NODE, str(HARNESS), str(page), str(len(NUMBERS[fuel]))], env=NODE_ENV,
                                        capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            checks = json.loads(result.stdout)
            self.assertGreaterEqual(len(checks), 30)
            failed = [name for name, ok in checks.items() if not ok]
            self.assertEqual(failed, [], f"{fuel}: failed browser-behaviour checks: {failed}")
