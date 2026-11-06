"""
"مجموع اطلاعات" on "دفتر موجودی و عملیات" (screen + PDF).

The expected totals below are worked out BY HAND from the raw inputs
(purchases, meter readings, tests, entered actual inventory), not from the
report code, then compared with (a) the service, (b) the on-screen cards,
and (c) the PDF's summary row.

Day-by-day fixture (Regular tank, opening inventory 100,000). Theoretical inventory is
total - (sales + test) -- the test liters go back into the tank -- so each actual below is the
perfect-day figure for that day (carried-over liters included) plus the intended سرک/کسری:
  d1: total 115,010, theoretical 112,010 -> actual 112,510 = +500 (سرک)
  d2: total 121,015 (112,510 + 8,000 + 5 + 500), theoretical 118,515 -> actual 117,985 = -530 (کسری)
  d3: total 117,985, theoretical 116,785 -> actual 116,785 = 0
  d4: total 136,805 (116,785 + 20,000 + 20), theoretical 134,505 -> actual 134,805 = +300 (سرک)


 day  purchases        meters        test  sales  actual   -> سرک / کسری
 08-01 10,000 + 5,000  0 -> 3,000     10   2,990  112,510     سرک 500
 08-02  8,000          3,000 -> 5,500   5   2,495  117,985     کسری 530
 08-03  --             5,500 -> 6,700   0   1,200  116,785     0 / 0
 08-04 20,000          6,700 -> 9,000  20   2,280  134,805     سرک 300
 08-05  --             9,000 -> 9,500   5     495  (not entered)  blank

 whole range: خرید 43,000 | سرک 800 | آزمایش 40 | فروش 9,460 | کسری 530
 08-02..08-04: خرید 28,000 | سرک 300 | آزمایش 25 | فروش 5,975 | کسری 530
"""

import datetime
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.core.test_number_display import pdf_text, render_pdf_with_html
from apps.inventory.models import OpeningInventory, TankInventory
from apps.license.models import License
from apps.purchases.models import PurchaseInvoice
from apps.reports import services as report_services
from apps.sales.models import NozzleSale, SalesInvoice
from apps.stations.models import Nozzle, Product, Station, Tank
from apps.workday.models import DailyWorkingDay

User = get_user_model()

WHOLE_RANGE = ("2026-08-01", "2026-08-05")
MIDDLE_RANGE = ("2026-08-02", "2026-08-04")

EXPECTED_WHOLE = {
    "purchase": "43,000", "overage": "800", "test-received": "40",
    "sales": "9,460", "shortage": "530", "test-dispatched": "40",
}
EXPECTED_MIDDLE = {
    "purchase": "28,000", "overage": "300", "test-received": "25",
    "sales": "5,975", "shortage": "530", "test-dispatched": "25",
}


def screen_totals(html):
    return dict(re.findall(r'data-total="([a-z-]+)"[^>]*>([^<]*)<', html))


def pdf_summary_values(html):
    """The six values in the PDF's summary row (first print-summary table)."""
    block = html.split("print-summary", 1)[1].split("</table>", 1)[0]
    return [v.strip() for v in re.findall(r'class="numeric"[^>]*>([^<]*)<', block)]


class LedgerTotalsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="Koohi 118", province="Razavi Khorasan", city="Mashhad")
        regular = Product.objects.create(name="Regular")
        sup = Product.objects.create(name="CNG")
        self.tank = Tank.objects.create(station=station, product=regular, capacity=50000)
        self.super_tank = Tank.objects.create(station=station, product=sup, capacity=30000)
        self.nozzle = Nozzle.objects.create(tank=self.tank, number=1)
        self.super_nozzle = Nozzle.objects.create(tank=self.super_tank, number=19)
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("100000"), effective_month=datetime.date(2026, 7, 23)
        )
        OpeningInventory.objects.create(
            tank=self.super_tank, opening_quantity=Decimal("50000"), effective_month=datetime.date(2026, 7, 23)
        )
        self.client.login(username="op1", password="testpass123")

        days = [
            # date, purchases, prev, new, test, actual
            (1, [10000, 5000], 0, 3000, 10, "112510"),
            (2, [8000], 3000, 5500, 5, "117985"),
            (3, [], 5500, 6700, 0, "116785"),
            (4, [20000], 6700, 9000, 20, "134805"),
            (5, [], 9000, 9500, 5, None),
        ]
        for day, purchases, prev, new, test, actual in days:
            wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, day))
            invoice = SalesInvoice.objects.create(working_day=wd, operator=self.user)
            NozzleSale.objects.create(
                sales_invoice=invoice, nozzle=self.nozzle, previous_meter=Decimal(prev),
                new_meter=Decimal(new), test=Decimal(test), sales_rate=Decimal("1200"),
            )
            for qty in purchases:
                PurchaseInvoice.objects.create(
                    working_day=wd, tank=self.tank, quantity=qty, purchase_rate=Decimal("1200"),
                    program_number=f"P{day}{qty}", tanker_number=f"T{day}",
                )
            if actual is not None:
                TankInventory.objects.create(tank=self.tank, working_day=wd, actual_inventory=Decimal(actual))
            # CNG tank: unrelated data that must never leak into the Regular totals.
            NozzleSale.objects.create(
                sales_invoice=invoice, nozzle=self.super_nozzle, previous_meter=Decimal("0") + day * 100,
                new_meter=Decimal("0") + day * 100 + 77, test=Decimal("3"), sales_rate=Decimal("1500"),
            )
            PurchaseInvoice.objects.create(
                working_day=wd, tank=self.super_tank, quantity=999, purchase_rate=Decimal("1500"),
                program_number=f"S{day}", tanker_number=f"S{day}",
            )

    def url(self, rng, tank=None):
        tank = tank or self.tank
        return f"/reports/petroleum-ledger/?tank_id={tank.id}&start_date={rng[0]}&end_date={rng[1]}"

    def print_url(self, rng, tank=None):
        tank = tank or self.tank
        return f"/print/petroleum-ledger/{tank.id}/?start_date={rng[0]}&end_date={rng[1]}"

    # --- the service -----------------------------------------------------

    def test_fixture_rows_match_the_hand_worked_table(self):
        """Sanity check of my hand calculation against the live ledger rows."""
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 8, 1), datetime.date(2026, 8, 5)
        )
        self.assertEqual([r["overage"] for r in rows], [500, 0, 0, 300, None])
        self.assertEqual([r["shortage"] for r in rows], [0, 530, 0, 0, None])
        self.assertEqual([r["daily_sales"] for r in rows], [2990, 2495, 1200, 2280, 495])
        self.assertEqual([r["test_return"] for r in rows], [10, 5, 0, 20, 5])

    def test_service_totals_equal_hand_worked_sums(self):
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 8, 1), datetime.date(2026, 8, 5)
        )
        totals = report_services.petroleum_inventory_ledger_totals(rows)
        self.assertEqual(totals["total_purchase"], 43000)
        self.assertEqual(totals["total_overage"], 800)
        self.assertEqual(totals["total_test_received"], 40)
        self.assertEqual(totals["total_sales"], 9460)
        self.assertEqual(totals["total_shortage"], 530)
        self.assertEqual(totals["total_test_dispatched"], 40)

    def test_totals_equal_sum_of_the_displayed_row_values(self):
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 8, 1), datetime.date(2026, 8, 5)
        )
        totals = report_services.petroleum_inventory_ledger_totals(rows)
        self.assertEqual(totals["total_purchase"], sum(
            r["quantity"] for row in rows for r in row["received_rows"] if r["quantity"] is not None))
        self.assertEqual(totals["total_overage"], sum(r["overage"] for r in rows if r["overage"] is not None))
        self.assertEqual(totals["total_shortage"], sum(r["shortage"] for r in rows if r["shortage"] is not None))
        self.assertEqual(totals["total_sales"], sum(r["daily_sales"] for r in rows))
        self.assertEqual(totals["total_test_dispatched"], sum(r["test_return"] for r in rows))

    def test_empty_rows_give_zero_totals(self):
        totals = report_services.petroleum_inventory_ledger_totals([])
        self.assertTrue(all(v == 0 for v in totals.values()))

    # --- screen ----------------------------------------------------------

    def test_screen_shows_each_total_for_a_multi_record_range(self):
        resp = self.client.get(self.url(WHOLE_RANGE))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("مجموع اطلاعات", html)
        self.assertEqual(screen_totals(html), EXPECTED_WHOLE)

    def test_screen_labels_are_present_in_the_requested_order(self):
        html = self.client.get(self.url(WHOLE_RANGE)).content.decode()
        block = html.split('id="ledger-totals"', 1)[1].split("</table>", 1)[0]
        labels = re.findall(r'<div class="form-label">([^<]+)</div>', block)
        self.assertEqual(
            labels,
            ["مجموع خرید", "مجموع سرک", "مجموع آزمایش", "مجموع فروش", "مجموع کسری", "مجموع آزمایش"],
        )

    def test_summary_sits_above_the_main_table(self):
        html = self.client.get(self.url(WHOLE_RANGE)).content.decode()
        self.assertLess(html.index('id="ledger-totals"'), html.index("<table"))

    def test_totals_follow_the_selected_date_range(self):
        whole = screen_totals(self.client.get(self.url(WHOLE_RANGE)).content.decode())
        middle = screen_totals(self.client.get(self.url(MIDDLE_RANGE)).content.decode())
        self.assertEqual(middle, EXPECTED_MIDDLE)
        self.assertNotEqual(whole, middle)
        one_day = screen_totals(self.client.get(self.url(("2026-08-01", "2026-08-01"))).content.decode())
        self.assertEqual(one_day["purchase"], "15,000")        # two invoices that day
        self.assertEqual(one_day["overage"], "500")
        self.assertEqual(one_day["sales"], "2,990")

    def test_other_tanks_never_leak_into_the_totals(self):
        html = self.client.get(self.url(WHOLE_RANGE, tank=self.super_tank)).content.decode()
        totals = screen_totals(html)
        self.assertEqual(totals["purchase"], "4,995")           # 5 x 999 only
        self.assertEqual(totals["test-received"], "15")         # 5 x 3

    def test_no_summary_when_there_are_no_rows_or_no_tank(self):
        empty = self.client.get(self.url(("2026-09-20", "2026-09-21"))).content.decode()
        self.assertNotIn('id="ledger-totals"', empty)
        no_tank = self.client.get("/reports/petroleum-ledger/").content.decode()
        self.assertNotIn('id="ledger-totals"', no_tank)

    # --- PDF -------------------------------------------------------------

    def test_pdf_summary_matches_the_screen_for_both_ranges(self):
        for rng, expected in ((WHOLE_RANGE, EXPECTED_WHOLE), (MIDDLE_RANGE, EXPECTED_MIDDLE)):
            screen = screen_totals(self.client.get(self.url(rng)).content.decode())
            resp, html = render_pdf_with_html(self.client, self.print_url(rng))
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.content.startswith(b"%PDF"))
            pdf_values = pdf_summary_values(html)
            order = ["purchase", "overage", "test-received", "sales", "shortage", "test-dispatched"]
            self.assertEqual(pdf_values, [screen[k] for k in order], rng)
            self.assertEqual(pdf_values, [expected[k] for k in order], rng)

    def test_pdf_has_the_summary_above_the_table_with_all_labels(self):
        resp, html = render_pdf_with_html(self.client, self.print_url(WHOLE_RANGE))
        self.assertLess(html.index("مجموع اطلاعات"), html.index("جمع کل رسیده"))
        block = html.split("print-summary", 1)[1].split("</table>", 1)[0]
        labels = re.findall(r"<th>([^<]+)</th>", block)
        self.assertEqual(
            labels,
            ["مجموع خرید", "مجموع سرک", "مجموع آزمایش", "مجموع فروش", "مجموع کسری", "مجموع آزمایش"],
        )

    def test_pdf_file_text_contains_the_totals_and_the_ledger_still_prints(self):
        resp = self.client.get(self.print_url(WHOLE_RANGE))
        text = pdf_text(resp.content)
        for needle in ("مجموع اطلاعات", "43,000", "9,460", "دفتر موجودی و عملیات", "خارج شده"):
            self.assertIn(needle, text)

    def test_pdf_stays_a_single_landscape_page_for_a_small_range(self):
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(self.client.get(self.print_url(WHOLE_RANGE)).content))
        self.assertEqual(len(reader.pages), 1)
        box = reader.pages[0].mediabox
        self.assertGreater(float(box.width), float(box.height))

    # --- nothing stored / unrelated numbers untouched ---------------------

    def test_viewing_the_ledger_changes_no_stored_data(self):
        before = (
            list(TankInventory.objects.values_list("actual_inventory", flat=True).order_by("id")),
            list(PurchaseInvoice.objects.values_list("quantity", flat=True).order_by("id")),
            list(NozzleSale.objects.values_list("new_meter", flat=True).order_by("id")),
        )
        self.client.get(self.url(WHOLE_RANGE))
        self.client.get(self.print_url(WHOLE_RANGE))
        after = (
            list(TankInventory.objects.values_list("actual_inventory", flat=True).order_by("id")),
            list(PurchaseInvoice.objects.values_list("quantity", flat=True).order_by("id")),
            list(NozzleSale.objects.values_list("new_meter", flat=True).order_by("id")),
        )
        self.assertEqual(before, after)
