import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.inventory.models import OpeningInventory, TankInventory
from apps.license.models import License
from apps.purchases.models import PurchaseInvoice
from apps.stations.models import Product, Station, Tank
from apps.statement.models import StatementEntry
from apps.workday.models import DailyWorkingDay

from .models import DigitalEntry
from .services import build_digital_rows, build_mechanical_rows

User = get_user_model()


class ComparisonServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op_cmp", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S_cmp", province="P", city="C")
        self.regular = Product.objects.create(name="بنزین معمولی")
        self.super_ = Product.objects.create(name="بنزین سوپر")
        self.regular_tank = Tank.objects.create(station=station, product=self.regular, capacity=50000)
        self.super_tank = Tank.objects.create(station=station, product=self.super_, capacity=50000)
        self.client.login(username="op_cmp", password="testpass123")
        self.day1 = datetime.date(2026, 7, 23)  # Jalali 1405/05/01

    def test_mechanical_rows_match_statement_rows_exactly(self):
        """فروش مکانیکی must reuse apps.statement.services.build_statement_rows()
        verbatim -- same data sources/calculations as صورت وضعیت ماهانه."""
        from apps.statement.services import build_statement_rows

        wd1 = DailyWorkingDay.objects.create(date=self.day1)
        OpeningInventory.objects.create(
            tank=self.regular_tank, opening_quantity=Decimal("0"), effective_month=self.day1,
        )
        PurchaseInvoice.objects.create(
            working_day=wd1, tank=self.regular_tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"),
        )
        TankInventory.objects.create(tank=self.regular_tank, working_day=wd1, actual_inventory=Decimal("100"))

        expected = build_statement_rows(1405, 5)
        actual = build_mechanical_rows(1405, 5)
        self.assertEqual(actual, expected)

    def test_mechanical_rows_have_no_total_received_column_data_required(self):
        """Task 1's removal must hold here too: the template must not need
        row['total_received'] to render فروش مکانیکی -- confirmed via the
        view/template test below; here we just confirm the key still
        exists in the dict (reused as-is) but is simply not rendered."""
        rows = build_mechanical_rows(1405, 5)
        self.assertTrue(all("total_received" in row for row in rows))

    def test_digital_rows_always_one_per_tank(self):
        rows = build_digital_rows(1405, 5)
        self.assertEqual(len(rows), 2)
        products = {row["product"].name for row in rows}
        self.assertEqual(products, {"بنزین معمولی", "بنزین سوپر"})

    def test_digital_rows_default_to_zero(self):
        rows = build_digital_rows(1405, 5)
        for row in rows:
            self.assertEqual(row["beginning_inventory"], Decimal("0"))
            self.assertEqual(row["received_total"], Decimal("0"))
            self.assertEqual(row["dispatched_total"], Decimal("0"))

    def test_digital_entry_uses_separate_model_from_statement(self):
        """Critical requirement: فروش دیجیتال must be a separate DB
        table/model from StatementEntry (and from any mechanical source)."""
        self.assertNotEqual(DigitalEntry, StatementEntry)
        self.assertFalse(
            set(f.name for f in DigitalEntry._meta.get_fields())
            & {"digital_sales", "tanker_capacity"}
        )

    def test_digital_totals_are_plain_sums_of_entered_values_only(self):
        entry = DigitalEntry.objects.create(
            tank=self.regular_tank, year=1405, month=5,
            beginning_inventory=Decimal("100"), received_quantity=Decimal("50"),
            test_return=Decimal("2"), overage=Decimal("1"),
            sales_quantity=Decimal("40"), shortage=Decimal("3"), ending_inventory=Decimal("110"),
        )
        rows = build_digital_rows(1405, 5)
        row = next(r for r in rows if r["tank"] == self.regular_tank)
        self.assertEqual(row["received_total"], Decimal("153"))  # 100+50+2+1
        self.assertEqual(row["dispatched_total"], Decimal("155"))  # 40+2+3+110
        self.assertEqual(row["entry"].id, entry.id)

    def test_digital_values_are_never_derived_from_mechanical_data(self):
        """Creating heavy mechanical activity must not change an
        untouched DigitalEntry row at all."""
        wd1 = DailyWorkingDay.objects.create(date=self.day1)
        OpeningInventory.objects.create(
            tank=self.regular_tank, opening_quantity=Decimal("9999"), effective_month=self.day1,
        )
        PurchaseInvoice.objects.create(
            working_day=wd1, tank=self.regular_tank, quantity=Decimal("777"), purchase_rate=Decimal("1200"),
        )
        TankInventory.objects.create(tank=self.regular_tank, working_day=wd1, actual_inventory=Decimal("9999"))

        rows = build_digital_rows(1405, 5)
        row = next(r for r in rows if r["tank"] == self.regular_tank)
        self.assertEqual(row["beginning_inventory"], Decimal("0"))
        self.assertEqual(row["received_quantity"], Decimal("0"))


class ComparisonViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op_cmp_view", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S_cmp_view", province="P", city="C")
        self.product = Product.objects.create(name="بنزین معمولی")
        self.tank = Tank.objects.create(station=station, product=self.product, capacity=50000)
        self.client.login(username="op_cmp_view", password="testpass123")

    def test_page_loads_with_no_submit_button(self):
        resp = self.client.get("/comparison/?year=1405&month=5")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(">نمایش<", resp.content.decode())

    def test_page_shows_both_titles_and_required_columns(self):
        resp = self.client.get("/comparison/?year=1405&month=5")
        content = resp.content.decode()
        for label in [
            "فروش مکانیکی", "فروش دیجیتال", "رسیده", "خارج شده",
            "موجودی اول ماه", "مقدار رسیده", "سرک", "جمع کل",
            "مقدار فروش", "کسری", "موجودی آخر ماه", "جمع کل خارج شده",
        ]:
            self.assertIn(label, content)

    def test_month_selector_offers_exactly_twelve_months(self):
        """Bug fix: {% for m in "123456789101112" %} iterates that STRING
        character by character (15 chars), producing 15 options instead
        of 12 -- now it's 12 explicit options, same fix as گزارش ماهانه
        مخازن and صورت وضعیت ماهانه."""
        resp = self.client.get("/comparison/?year=1405&month=5")
        content = resp.content.decode()
        self.assertEqual(content.count('<option value="'), 12)
        for m in range(1, 13):
            self.assertIn(f'<option value="{m}"', content)
        for m in range(13, 16):
            self.assertNotIn(f'<option value="{m}"', content)

    def test_mechanical_section_order_before_digital(self):
        resp = self.client.get("/comparison/?year=1405&month=5")
        content = resp.content.decode()
        self.assertLess(content.index("فروش مکانیکی"), content.index("فروش دیجیتال"))

    def test_total_received_column_not_reintroduced(self):
        resp = self.client.get("/comparison/?year=1405&month=5")
        self.assertNotIn("جمع کل رسیده ها", resp.content.decode())

    def test_digital_entry_form_is_centered(self):
        """UI fix: the form panel must be centered (margin: 0 auto), like
        the existing فاکتورهای فروش / واریزی‌ها forms, not stuck to the
        right edge."""
        entry = DigitalEntry.objects.create(tank=self.tank, year=1405, month=5)
        resp = self.client.get(f"/comparison/entry/{entry.id}/edit/")
        self.assertIn("margin: 0 auto", resp.content.decode())

    def test_digital_entry_edit_saves_and_redirects(self):
        entry = DigitalEntry.objects.create(tank=self.tank, year=1405, month=5)
        resp = self.client.post(
            f"/comparison/entry/{entry.id}/edit/",
            {
                "beginning_inventory": "10", "received_quantity": "20", "test_return": "1",
                "overage": "0", "sales_quantity": "15", "shortage": "0", "ending_inventory": "16",
            },
        )
        self.assertEqual(resp.status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(entry.received_quantity, Decimal("20"))
        self.assertEqual(entry.ending_inventory, Decimal("16"))


class ComparisonPrintContextTests(TestCase):
    def setUp(self):
        station = Station.objects.create(name="S_cmp_print", province="P", city="C")
        self.product = Product.objects.create(name="بنزین معمولی")
        Tank.objects.create(station=station, product=self.product, capacity=50000)

    def test_pdf_source_html_has_both_titles_in_order_and_no_total_received(self):
        from django.template.loader import render_to_string

        from apps.printing.services import build_comparison_context

        context = build_comparison_context(1405, 5)
        html = render_to_string("printing/comparison_print.html", context)

        self.assertLess(html.index("فروش مکانیکی"), html.index("فروش دیجیتال"))
        self.assertNotIn("جمع کل رسیده ها", html)
