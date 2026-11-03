"""
The auto-filled "کنتور قبلی" in the new-entry form of فاکتورهای فروش is shown
as an integer (no ".00"), display only.
"""

import datetime
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.license.models import License
from apps.sales.models import NozzleSale, SalesInvoice
from apps.stations.models import Nozzle, Product, Station, Tank
from apps.workday.models import DailyWorkingDay

User = get_user_model()
D = Decimal


def input_value(html, field):
    m = re.search(rf'<input[^>]*name="{field}"[^>]*>', html)
    assert m, f"no input named {field}"
    v = re.search(r'value="([^"]*)"', m.group(0))
    return v.group(1) if v else None


class PreviousMeterDisplayTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S", province="P", city="C")
        self.tank = Tank.objects.create(station=station, product=Product.objects.create(name="Regular"), capacity=50000)
        self.n1 = Nozzle.objects.create(tank=self.tank, number=1)
        self.n2 = Nozzle.objects.create(tank=self.tank, number=2)
        self.client.login(username="op1", password="testpass123")

    def yesterday_sale(self, nozzle, new_meter, prev="0", test="0", rate="1200"):
        wd, _ = DailyWorkingDay.objects.get_or_create(date=datetime.date(2026, 8, 1))
        inv, _ = SalesInvoice.objects.get_or_create(working_day=wd, defaults={"operator": self.user})
        return NozzleSale.objects.create(sales_invoice=inv, nozzle=nozzle, previous_meter=D(prev),
                                         new_meter=D(new_meter), test=D(test), sales_rate=D(rate))

    def page(self, nozzle=1, date="2026-08-02"):
        resp = self.client.get(f"/sales/invoices/{date}/nozzle/{nozzle}/")
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    # --- the displayed value -------------------------------------------------

    def test_whole_number_previous_meter_has_no_decimal_tail(self):
        self.yesterday_sale(self.n1, "1334572")
        html = self.page()
        self.assertEqual(input_value(html, "previous_meter"), "1334572")
        self.assertNotIn("1334572.00", html)

    def test_various_whole_values_are_plain_integers_never_scientific(self):
        for stored, shown in (("150", "150"), ("1000", "1000"), ("100", "100"), ("20", "20"),
                              ("1000000", "1000000"), ("48200", "48200")):
            NozzleSale.objects.all().delete()
            self.yesterday_sale(self.n1, stored)
            self.assertEqual(input_value(self.page(), "previous_meter"), shown, stored)

    def test_meaningful_fractions_are_kept(self):
        for stored, shown in (("100.50", "100.5"), ("1234.75", "1234.75"), ("0.25", "0.25"), ("9.05", "9.05")):
            NozzleSale.objects.all().delete()
            self.yesterday_sale(self.n1, stored)
            self.assertEqual(input_value(self.page(), "previous_meter"), shown, stored)

    def test_it_is_still_the_previous_days_new_meter(self):
        self.yesterday_sale(self.n1, "5555")
        self.yesterday_sale(self.n2, "7777")
        self.assertEqual(input_value(self.page(1), "previous_meter"), "5555")
        self.assertEqual(input_value(self.page(2), "previous_meter"), "7777")

    def test_first_ever_entry_still_blank(self):
        self.assertIn(input_value(self.page(), "previous_meter"), (None, ""))

    def test_other_fields_are_unchanged_by_this_task(self):
        self.yesterday_sale(self.n1, "150", rate="1200")
        html = self.page()
        self.assertEqual(input_value(html, "sales_rate"), "1200.00")     # suggested rate: as before
        self.assertIn(input_value(html, "new_meter"), (None, ""))
        self.assertEqual(input_value(html, "test"), "0")          # model default, as before

    def test_editing_an_existing_record_shows_the_trimmed_value_too(self):
        self.yesterday_sale(self.n1, "35", prev="10")
        html = self.page(1, "2026-08-01")
        self.assertEqual(input_value(html, "previous_meter"), "10")
        self.assertEqual(input_value(html, "new_meter"), "35.00")        # editable fields otherwise as before

    # --- stored values and calculations are untouched -------------------------

    def test_stored_values_are_unchanged_by_viewing(self):
        sale = self.yesterday_sale(self.n1, "1334572.00")
        self.page()
        sale.refresh_from_db()
        self.assertEqual(sale.new_meter, D("1334572.00"))
        self.assertEqual(str(sale.new_meter), "1334572.00")

    def test_saving_the_displayed_integer_gives_identical_stored_values_and_math(self):
        self.yesterday_sale(self.n1, "1334572")
        shown = input_value(self.page(1), "previous_meter")
        self.assertEqual(shown, "1334572")
        resp = self.client.post("/sales/invoices/2026-08-02/nozzle/1/", {
            "previous_meter": shown, "new_meter": "1335000.5", "test": "5", "sales_rate": "1200"})
        self.assertEqual(resp.status_code, 302)
        sale = NozzleSale.objects.get(sales_invoice__working_day__date=datetime.date(2026, 8, 2), nozzle=self.n1)
        self.assertEqual(sale.previous_meter, D("1334572"))
        self.assertEqual(str(sale.previous_meter), "1334572.00")          # stored with the same scale as before
        self.assertEqual(sale.operation, D("428.50"))
        self.assertEqual(sale.mechanical_sales, D("423.50"))
        self.assertEqual(sale.total_amount, D("423.50") * D("1200"))

    def test_submitting_with_and_without_the_tail_is_equivalent(self):
        results = []
        for i, value in enumerate(("500", "500.00")):
            NozzleSale.objects.all().delete(); SalesInvoice.objects.all().delete(); DailyWorkingDay.objects.all().delete()
            self.client.post("/sales/invoices/2026-08-01/nozzle/1/", {
                "previous_meter": value, "new_meter": "650", "test": "0", "sales_rate": "1200"})
            s = NozzleSale.objects.get()
            results.append((s.previous_meter, s.new_meter, s.operation, s.mechanical_sales, s.total_amount))
        self.assertEqual(results[0], results[1])

    def test_negative_movement_warning_flow_still_works(self):
        self.yesterday_sale(self.n1, "1000")
        resp = self.client.post("/sales/invoices/2026-08-02/nozzle/1/", {
            "previous_meter": "1000", "new_meter": "900", "test": "0", "sales_rate": "1200"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "هشدار")
        resp = self.client.post("/sales/invoices/2026-08-02/nozzle/1/", {
            "previous_meter": "1000", "new_meter": "900", "test": "0", "sales_rate": "1200",
            "confirm_negative_meter": "1"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(NozzleSale.objects.get(nozzle=self.n1, sales_invoice__working_day__date=datetime.date(2026, 8, 2)).operation, D("-100"))

    def test_tables_and_other_screens_unchanged(self):
        self.yesterday_sale(self.n1, "1334572", prev="1000000")
        resp = self.client.get("/sales/invoices/2026-08-01/")
        self.assertContains(resp, "1,334,572")
        self.assertNotContains(resp, "1334572.00")
