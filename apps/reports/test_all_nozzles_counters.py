"""
لیست اطلاعات فروش: the monthly counter columns کنتور اول ماه / کنتور آخر ماه, per fuel.

  کنتور اول ماه = کنتور قبلی of the nozzle's FIRST RECORDED working day in the month
  کنتور آخر ماه = کنتور جدید of the nozzle's LAST RECORDED working day in the month

Taken from the real فاکتورهای فروش records -- never from the 1st / last calendar day,
never from record creation order. A nozzle with no record that month shows "—" (a
missing record is not a reading of 0), while a real 0 shows as 0.

Extra hand data on top of test_all_nozzles_report.AllNozzlesBase (its months 1405/05
and 1405/06 are reused unchanged):

JALALI 1405/07 (2026-09-23 .. 2026-10-22) -- records created OUT OF ORDER, with gaps:
  Regular nozzle 3 : created 2026-10-02 (700 -> 900, test 0) THEN 2026-09-25 (100 -> 700, test 5), @1200
             first = 100 (not 700, the lowest id) | last = 900
             operation 800 | test 5 | sales 795 | amount 795 x 1200 = 954,000
  Regular nozzle 2 : 2026-10-20 only (900 -> 950)   first 900 | last 950 | 50 | 0 | 50 | 60,000
  Super   nozzle 20: created 2026-10-10 (50 -> 80) THEN 2026-09-24 (0 -> 50), @1500
             first = 0 | last = 80 | operation 80 | test 0 | sales 80 | amount 120,000
  REGULAR totals: 850 | 5 | 845 | 1,014,000        SUPER totals: 80 | 0 | 80 | 120,000
JALALI 1405/08 (from 2026-10-23): Regular nozzle 5: 2026-10-25, 0 -> 300000 (the brief's example)
"""

import datetime
import re
from decimal import Decimal

from apps.core.test_number_display import pdf_text, render_pdf_with_html
from apps.reports import services as report_services
from apps.reports.test_all_nozzles_report import (
    DATA_05, DATA_06, FIELDS, FIRST_LAST_05, FIRST_LAST_06, NUMBERS, TOTALS_05, AllNozzlesBase,
    expected_row, fmt, pdf_summary, pdf_table_rows, screen_totals, table_rows,
)
from apps.sales.models import NozzleSale

D = Decimal
DATA_07 = {3: (800, 5, 795, 954000), 2: (50, 0, 50, 60000), 20: (80, 0, 80, 120000)}
FIRST_LAST_07 = {3: (100, 900), 2: (900, 950), 20: (0, 80)}
TOTALS_07 = {"Regular": (850, 5, 845, 1014000), "Super": (80, 0, 80, 120000)}
DATA_08 = {5: (300000, 0, 300000, 360000000)}
FIRST_LAST_08 = {5: (0, 300000)}

MONTHS = {5: (DATA_05, FIRST_LAST_05), 6: (DATA_06, FIRST_LAST_06), 7: (DATA_07, FIRST_LAST_07),
          8: (DATA_08, FIRST_LAST_08), 9: ({}, {})}


class CounterBase(AllNozzlesBase):
    def setUp(self):
        super().setUp()
        day = datetime.date
        # month 07, deliberately created in reverse chronological order, with gaps around them
        self.add_sale(day(2026, 10, 2), 3, 700, 900, 0)
        self.add_sale(day(2026, 9, 25), 3, 100, 700, 5)
        self.add_sale(day(2026, 10, 20), 2, 900, 950, 0)
        self.add_sale(day(2026, 10, 10), 20, 50, 80, 0, 1500)
        self.add_sale(day(2026, 9, 24), 20, 0, 50, 0, 1500)
        # month 08: the brief's example
        self.add_sale(day(2026, 10, 25), 5, 0, 300000, 0)


class ServiceCounterTests(CounterBase):
    def rows(self, month, fuel):
        return report_services.all_nozzles_monthly_summary(1405, month, self.tank[fuel])

    def test_first_and_last_counters_per_nozzle_and_fuel(self):
        for month, (_, first_last) in MONTHS.items():
            for fuel in ("Regular", "Super"):
                for row in self.rows(month, fuel):
                    first, last = first_last.get(row["nozzle_number"], (None, None))
                    self.assertEqual(row["first_meter"], None if first is None else D(first), (month, fuel, row["nozzle_number"]))
                    self.assertEqual(row["last_meter"], None if last is None else D(last), (month, fuel, row["nozzle_number"]))

    def test_counters_match_the_underlying_sales_records(self):
        """Independently, straight from the فاکتورهای فروش rows: earliest day's کنتور قبلی, latest day's کنتور جدید."""
        ranges = {5: (datetime.date(2026, 7, 23), datetime.date(2026, 8, 22)),
                  7: (datetime.date(2026, 9, 23), datetime.date(2026, 10, 22))}
        for month, (start, end) in ranges.items():
            for fuel in ("Regular", "Super"):
                for row in self.rows(month, fuel):
                    sales = sorted(NozzleSale.objects.filter(nozzle__number=row["nozzle_number"],
                                                             sales_invoice__working_day__date__range=(start, end)),
                                   key=lambda s: s.sales_invoice.working_day.date)
                    if not sales:
                        self.assertIsNone(row["first_meter"]); self.assertIsNone(row["last_meter"])
                    else:
                        self.assertEqual(row["first_meter"], sales[0].previous_meter, (month, row["nozzle_number"]))
                        self.assertEqual(row["last_meter"], sales[-1].new_meter, (month, row["nozzle_number"]))

    def test_uses_recorded_days_not_calendar_edges_or_creation_order(self):
        regular = {r["nozzle_number"]: r for r in self.rows(7, "Regular")}[3]
        self.assertEqual((regular["first_meter"], regular["last_meter"]), (D(100), D(900)))
        sup = {r["nozzle_number"]: r for r in self.rows(7, "Super")}[20]
        self.assertEqual((sup["first_meter"], sup["last_meter"]), (D(0), D(80)))

    def test_existing_calculations_and_per_fuel_totals_are_unchanged(self):
        for month, (data, _) in MONTHS.items():
            for fuel in ("Regular", "Super"):
                rows = self.rows(month, fuel)
                for r in rows:
                    op, test, sales, amount = data.get(r["nozzle_number"], (0, 0, 0, 0))
                    self.assertEqual((r["total_operation"], r["total_test"], r["total_mechanical_sales"], r["total_amount"]),
                                     (D(op), D(test), D(sales), D(amount)), (month, fuel, r["nozzle_number"]))
        for fuel in ("Regular", "Super"):
            t = report_services.all_nozzles_monthly_totals(self.rows(7, fuel))
            self.assertEqual(tuple(t[f] for f in FIELDS), tuple(D(x) for x in TOTALS_07[fuel]), fuel)
            t = report_services.all_nozzles_monthly_totals(self.rows(5, fuel))
            self.assertEqual(tuple(t[f] for f in FIELDS), tuple(D(x) for x in TOTALS_05[fuel]), fuel)

    def test_nozzle_order_is_kept_for_every_month_and_fuel(self):
        for month in MONTHS:
            for fuel in ("Regular", "Super"):
                self.assertEqual([r["nozzle_number"] for r in self.rows(month, fuel)], NUMBERS[fuel])


class ScreenCounterTests(CounterBase):
    def test_columns_values_and_missing_markers_for_both_fuels(self):
        for month, (data, first_last) in MONTHS.items():
            for fuel in ("Regular", "Super"):
                rows = table_rows(self.page(month, fuel))
                self.assertEqual([int(r[0]) for r in rows], NUMBERS[fuel])
                for r in rows:
                    self.assertEqual(r, expected_row(int(r[0]), data, first_last), (month, fuel, r[0]))

    def test_the_brief_example_zero_then_300000(self):
        rows = {int(r[0]): r for r in table_rows(self.page(8, "Regular"))}
        self.assertEqual(rows[5][:3], ["5", "0", "300,000"])

    def test_a_real_zero_is_shown_as_0_and_a_missing_record_as_a_dash(self):
        regular = {int(r[0]): r for r in table_rows(self.page(5, "Regular"))}
        self.assertEqual(regular[1][1], "0")                      # nozzle 1: first previous meter is 0
        self.assertEqual(regular[3][1:3], ["—", "—"])             # nozzle 3: no record in month 05
        sup = {int(r[0]): r for r in table_rows(self.page(5, "Super"))}
        self.assertEqual(sup[19][1], "0")
        self.assertEqual(sup[22][1:3], ["—", "—"])

    def test_sales_test_and_operation_keep_their_values(self):
        regular = {int(r[0]): r for r in table_rows(self.page(7, "Regular"))}
        self.assertEqual(regular[3][3:], ["795", "5", "800"])
        sup = {int(r[0]): r for r in table_rows(self.page(7, "Super"))}
        self.assertEqual(sup[20][3:], ["80", "0", "80"])

    def test_total_amount_is_gone_from_the_table_but_the_summary_keeps_it_per_fuel(self):
        for fuel in ("Regular", "Super"):
            html = self.page(7, fuel)
            head = html.split('id="all-nozzles-table"', 1)[1].split("</thead>", 1)[0]
            self.assertNotIn("جمع مبلغ کل", head)
            self.assertEqual(len(table_rows(html)[0]), 6)
            self.assertIn("مجموع مبلغ کل", html.split('id="all-nozzles-totals"', 1)[1].split("</div>\n  </div>", 1)[0])
            self.assertEqual(screen_totals(html), tuple(fmt(x) for x in TOTALS_07[fuel]))


class PdfCounterTests(CounterBase):
    def test_pdf_matches_the_screen_for_every_month_and_fuel(self):
        for month in MONTHS:
            for fuel in ("Regular", "Super"):
                screen = self.page(month, fuel)
                resp, html = render_pdf_with_html(self.client, self.print_url(month, fuel))
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.content.startswith(b"%PDF"))
                self.assertEqual(pdf_table_rows(html), table_rows(screen), (month, fuel))
                self.assertEqual(pdf_summary(html), screen_totals(screen), (month, fuel))

    def test_pdf_columns_in_order_and_summary_keeps_total_amount(self):
        for fuel in ("Regular", "Super"):
            _, html = render_pdf_with_html(self.client, self.print_url(7, fuel))
            summary, main = html.split("print-summary", 1)[1].split("</table>", 1)
            self.assertIn("مجموع مبلغ کل", summary)
            self.assertNotIn("جمع مبلغ کل", main)
            head = main.split("<thead>", 1)[1].split("</thead>", 1)[0]
            self.assertEqual(re.findall(r"<th[^>]*>([^<]*)</th>", head),
                             ["شماره نازل", "کنتور اول ماه", "کنتور آخر ماه", "جمع فروش مکانیکی", "جمع آزمایش", "جمع کارکرد"])
            self.assertEqual(pdf_summary(html), tuple(fmt(x) for x in TOTALS_07[fuel]))

    def test_pdf_example_values_and_file_text(self):
        _, html = render_pdf_with_html(self.client, self.print_url(8, "Regular"))
        rows = {int(r[0]): r for r in pdf_table_rows(html)}
        self.assertEqual(rows[5][:3], ["5", "0", "300,000"])
        text = pdf_text(self.client.get(self.print_url(7, "Regular")).content)
        for needle in ("1,014,000", "795", "900", "کنتور"):
            self.assertIn(needle, text)
        self.assertNotIn("954,000", text)                         # per-nozzle amounts are no longer printed

    def test_viewing_changes_no_stored_data(self):
        before = list(NozzleSale.objects.values_list("id", "previous_meter", "new_meter", "test", "sales_rate").order_by("id"))
        for month in (5, 7, 8):
            for fuel in ("Regular", "Super"):
                self.page(month, fuel)
                self.client.get(self.print_url(month, fuel))
        self.assertEqual(before, list(NozzleSale.objects.values_list(
            "id", "previous_meter", "new_meter", "test", "sales_rate").order_by("id")))
