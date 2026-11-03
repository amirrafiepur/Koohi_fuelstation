"""
"مقدار لیتراژ کسری غیرمجازه" (لیتراژ غیرمجاز) in صورت وضعیت ماهانه is DISPLAYED
only when "پورسانت" >= 45; below that 0 is shown (screen and PDF). The
calculation itself is unchanged.

Hand-worked fixture, JALALI 1405/05 -- one working day per tank, opening
inventory 100,000, purchase 10,000, mechanical sales 1,000, no test:
    total = 100,000 + 10,000 = 110,000 ; theoretical = 110,000 - 1,000 = 109,000
    actual = 109,000 - X  ->  shortage X
    commission = X x 10000 / 10,000 = X ; allowed = 10,000 x 45 / 10000 = 45
    unauthorized = X - 45
  X = 50 -> commission 50.00 (>= 45): unauthorized 5.00 is shown
  X = 30 -> commission 30.00 (<  45): calculated -15.00, but 0 is shown
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
from apps.sales.models import NozzleSale, SalesInvoice
from apps.statement.services import build_statement_rows
from apps.stations.models import Nozzle, Product, Station, Tank
from apps.workday.models import DailyWorkingDay

User = get_user_model()
D = Decimal
DAY = datetime.date(2026, 7, 24)           # Jalali 1405/05/02


def lower_table_rows(html, nth_table):
    """Cell texts of the body rows of the nth <table> (0-based) on the page."""
    table = html.split("<table")[nth_table + 1].split("</table>", 1)[0]
    body = table.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return [
        [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S)
    ]


class UnauthorizedDisplayBase(TestCase):
    def make_tank(self, station, name, nozzle_number, purchase, shortage, sales=1000):
        tank = Tank.objects.create(station=station, product=Product.objects.create(name=name), capacity=50000)
        nozzle = Nozzle.objects.create(tank=tank, number=nozzle_number)
        OpeningInventory.objects.create(tank=tank, opening_quantity=D("100000"), effective_month=datetime.date(2026, 7, 23))
        wd, _ = DailyWorkingDay.objects.get_or_create(date=DAY)
        inv, _ = SalesInvoice.objects.get_or_create(working_day=wd, defaults={"operator": self.user})
        NozzleSale.objects.create(sales_invoice=inv, nozzle=nozzle, previous_meter=D("0"), new_meter=D(sales),
                                  test=D("0"), sales_rate=D("1200"))
        PurchaseInvoice.objects.create(working_day=wd, tank=tank, quantity=purchase, purchase_rate=D("1200"),
                                       program_number="1", tanker_number="T")
        theoretical = D("100000") + purchase - D(sales)
        TankInventory.objects.create(tank=tank, working_day=wd, actual_inventory=theoretical - D(str(shortage)))
        return tank

    def setUp(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        self.station = Station.objects.create(name="140 Jahan Pour", province="Razavi Khorasan", city="Mashhad")
        self.client.login(username="op1", password="testpass123")

    def rows_by_name(self):
        return {r["product"].name: r for r in build_statement_rows(1405, 5)}


class ServiceTests(UnauthorizedDisplayBase):
    def setUp(self):
        super().setUp()
        self.make_tank(self.station, "Regular", 1, 10000, 50)
        self.make_tank(self.station, "Super", 19, 10000, 30)

    def test_calculation_is_untouched(self):
        rows = self.rows_by_name()
        for name, shortage, commission, unauthorized in (("Regular", 50, "50.00", "5.00"), ("Super", 30, "30.00", "-15.00")):
            self.assertEqual(rows[name]["total_shortage"], D(shortage))
            self.assertEqual(rows[name]["commission"], D(commission))
            self.assertEqual(rows[name]["allowed_shortage"], D("45.00"))
            self.assertEqual(rows[name]["unauthorized_shortage"], D(unauthorized))      # the formula's own result

    def test_displayed_value_follows_the_threshold(self):
        rows = self.rows_by_name()
        self.assertEqual(rows["Regular"]["unauthorized_shortage_shown"], D("5.00"))     # commission 50 >= 45
        self.assertEqual(rows["Super"]["unauthorized_shortage_shown"], D("0.00"))       # commission 30 <  45

    def test_boundary_values(self):
        """Exactly 45 shows the calculated value (which is 0 there); 45.01 shows it; 44.99 shows 0."""
        for sales, shortage, purchase, commission, calculated, shown in (
            (1000, "90", 20000, "45.00", "0.00", "0.00"),
            (1000, "90.02", 20000, "45.01", "0.02", "0.02"),
            (1000, "89.98", 20000, "44.99", "-0.02", "0.00"),
        ):
            for m in (NozzleSale, TankInventory, OpeningInventory, PurchaseInvoice, SalesInvoice, DailyWorkingDay, Nozzle, Tank):
                m.objects.all().delete()
            Product.objects.all().delete()
            self.make_tank(self.station, "Regular", 1, purchase, shortage, sales)
            row = self.rows_by_name()["Regular"]
            self.assertEqual(row["commission"], D(commission), shortage)
            self.assertEqual(row["unauthorized_shortage"], D(calculated), shortage)
            self.assertEqual(row["unauthorized_shortage_shown"], D(shown), shortage)

    def test_month_without_purchases_shows_zero(self):
        rows = {r["product"].name: r for r in build_statement_rows(1405, 6)}
        self.assertEqual(rows["Regular"]["commission"], D("0.00"))
        self.assertEqual(rows["Regular"]["unauthorized_shortage_shown"], D("0.00"))


class ScreenAndPdfTests(UnauthorizedDisplayBase):
    def setUp(self):
        super().setUp()
        self.make_tank(self.station, "Regular", 1, 10000, 50)
        self.make_tank(self.station, "Super", 19, 10000, 30)

    def test_screen_shows_the_calculated_value_at_or_above_45_and_zero_below(self):
        html = self.client.get("/statement/?year=1405&month=5").content.decode()
        rows = {r[0]: r for r in lower_table_rows(html, 1)}
        regular, sup = rows["بنزین معمولی"], rows["بنزین سوپر"]
        self.assertEqual((regular[2], regular[3]), ("50", "5"))          # commission 50 -> 5.00 shown as 5
        self.assertEqual((sup[2], sup[3]), ("30", "0"))                  # commission 30 -> 0 (calculated -15 hidden)
        self.assertNotIn("-15", " ".join(sup))

    def test_pdf_shows_the_same_values(self):
        resp, html = render_pdf_with_html(self.client, "/print/statement/?year=1405&month=5")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b"%PDF"))
        rows = {r[0]: r for r in lower_table_rows(html, 1)}
        self.assertEqual((rows["بنزین معمولی"][2], rows["بنزین معمولی"][3]), ("50", "5"))
        self.assertEqual((rows["بنزین سوپر"][2], rows["بنزین سوپر"][3]), ("30", "0"))
        self.assertNotIn("-15", pdf_text(resp.content))

    def test_pdf_matches_the_screen_row_for_row(self):
        screen = lower_table_rows(self.client.get("/statement/?year=1405&month=5").content.decode(), 1)
        _, html = render_pdf_with_html(self.client, "/print/statement/?year=1405&month=5")
        pdf = lower_table_rows(html, 1)
        for s, p in zip(screen, pdf):
            self.assertEqual((s[0], s[2], s[3]), (p[0], p[2], p[3]))     # product, commission, unauthorized

    def test_the_rest_of_the_statement_is_unchanged(self):
        html = self.client.get("/statement/?year=1405&month=5").content.decode()
        upper = {r[0]: r for r in lower_table_rows(html, 0)}
        self.assertIn("بنزین معمولی", upper)
        for needle in ("پورسانت", "مقدار لیتراژ کسری غیرمجازه", "جمع کل رسیده", "تعداد نفتکش", "ظرفیت نفتکش"):
            self.assertIn(needle, html)

    def test_viewing_changes_no_stored_data(self):
        before = list(TankInventory.objects.values_list("actual_inventory", flat=True).order_by("id"))
        self.client.get("/statement/?year=1405&month=5")
        self.client.get("/print/statement/?year=1405&month=5")
        self.assertEqual(before, list(TankInventory.objects.values_list("actual_inventory", flat=True).order_by("id")))
