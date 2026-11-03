import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.inventory.models import OpeningInventory, TankInventory
from apps.license.models import License
from apps.purchases.models import PurchaseInvoice
from apps.sales.models import NozzleSale, SalesInvoice
from apps.stations.models import Nozzle, Product, Station, Tank
from apps.workday.models import DailyWorkingDay

from .models import StatementEntry
from .services import build_statement_rows

User = get_user_model()


class StatementServiceTests(TestCase):
    """
    Covers build_statement_rows(): reuse of
    apps.reports.services.petroleum_inventory_monthly() for every shared
    value, plus the section's own new formulas (جمع کل/جمع کل خارج شده,
    پورسانت, کسری غیرمجاز, تعداد نفتکش).
    """

    def setUp(self):
        self.user = User.objects.create_user(username="op_stmt", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S_stmt", province="P", city="C")
        self.regular = Product.objects.create(name="بنزین معمولی")
        self.super_ = Product.objects.create(name="بنزین سوپر")
        self.regular_tank = Tank.objects.create(station=station, product=self.regular, capacity=50000)
        self.super_tank = Tank.objects.create(station=station, product=self.super_, capacity=50000)
        self.nozzle = Nozzle.objects.create(tank=self.regular_tank, number=1)
        self.client.login(username="op_stmt", password="testpass123")
        # 2026-07-23 is Jalali 1405/05/01 -- see MonthlyTankStatementReworkTests
        # in apps/reports/tests.py for why this is the accounting start.
        self.day1 = datetime.date(2026, 7, 23)

    def _wd(self):
        return DailyWorkingDay.objects.create(date=self.day1)

    def test_always_one_row_per_tank_even_with_no_data(self):
        rows = build_statement_rows(1405, 5)
        self.assertEqual(len(rows), 2)
        products = {row["product"].name for row in rows}
        self.assertEqual(products, {"بنزین معمولی", "بنزین سوپر"})

    def test_main_table_totals_match_petroleum_inventory_monthly(self):
        wd1 = self._wd()
        OpeningInventory.objects.create(
            tank=self.regular_tank, opening_quantity=Decimal("0"), effective_month=self.day1,
        )
        PurchaseInvoice.objects.create(
            working_day=wd1, tank=self.regular_tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"),
        )
        TankInventory.objects.create(tank=self.regular_tank, working_day=wd1, actual_inventory=Decimal("100"))

        from apps.reports import services as report_services
        expected = report_services.petroleum_inventory_monthly(self.regular_tank, 1405, 5)

        rows = build_statement_rows(1405, 5)
        row = next(r for r in rows if r["tank"] == self.regular_tank)

        self.assertEqual(row["beginning_inventory"], expected["beginning_inventory"])
        self.assertEqual(row["total_purchase"], expected["total_purchase"])
        self.assertEqual(row["total_test_return"], expected["total_test_return"])
        self.assertEqual(row["total_overage"], expected["total_overage"])
        self.assertEqual(row["total_sales"], expected["total_sales"])
        self.assertEqual(row["total_shortage"], expected["total_shortage"])
        self.assertEqual(row["ending_inventory"], expected["ending_inventory"])
        self.assertEqual(row["total_received"], expected["total_received"])

    def test_received_total_formula(self):
        wd1 = self._wd()
        OpeningInventory.objects.create(
            tank=self.regular_tank, opening_quantity=Decimal("500"), effective_month=self.day1,
        )
        PurchaseInvoice.objects.create(
            working_day=wd1, tank=self.regular_tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"),
        )
        TankInventory.objects.create(tank=self.regular_tank, working_day=wd1, actual_inventory=Decimal("600"))

        rows = build_statement_rows(1405, 5)
        row = next(r for r in rows if r["tank"] == self.regular_tank)
        expected = row["beginning_inventory"] + row["total_purchase"] + row["total_test_return"] + row["total_overage"]
        self.assertEqual(row["received_total"], expected)

    def test_dispatched_total_uses_end_of_month_inventory_only(self):
        """
        جمع کل خارج شده = مقدار فروش + آزمایش + کسری + موجودی آخر ماه --
        per the task's explicit formula, deliberately NOT the ledger's own
        running per-day cumulative total (which adds every day's actual
        inventory, not just the last one).
        """
        wd1 = self._wd()
        OpeningInventory.objects.create(
            tank=self.regular_tank, opening_quantity=Decimal("0"), effective_month=self.day1,
        )
        PurchaseInvoice.objects.create(
            working_day=wd1, tank=self.regular_tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"),
        )
        TankInventory.objects.create(tank=self.regular_tank, working_day=wd1, actual_inventory=Decimal("100"))

        rows = build_statement_rows(1405, 5)
        row = next(r for r in rows if r["tank"] == self.regular_tank)
        expected = row["total_sales"] + row["total_test_return"] + row["total_shortage"] + row["ending_inventory"]
        self.assertEqual(row["dispatched_total"], expected)

    def test_commission_formula(self):
        """
        پورسانت = (کسری × 10000) ÷ مقدار رسیده -- using this exact
        fixture (کسری=5, مقدار رسیده=10), per the task's own stated
        verification: expected پورسانت = 5000.
        """
        wd1 = self._wd()
        OpeningInventory.objects.create(
            tank=self.regular_tank, opening_quantity=Decimal("0"), effective_month=self.day1,
        )
        PurchaseInvoice.objects.create(
            working_day=wd1, tank=self.regular_tank, quantity=Decimal("10"), purchase_rate=Decimal("1200"),
        )
        # Theoretical = 0 (opening) + 10 (purchase) + 0 (test) + 0 (overage) = 10.
        # Actual = 5 -> کسری (shortage) = 10 - 5 = 5.
        TankInventory.objects.create(tank=self.regular_tank, working_day=wd1, actual_inventory=Decimal("5"))

        rows = build_statement_rows(1405, 5)
        row = next(r for r in rows if r["tank"] == self.regular_tank)
        self.assertEqual(row["total_shortage"], Decimal("5"))
        self.assertEqual(row["total_purchase"], Decimal("10"))
        self.assertEqual(row["commission"], Decimal("5000.00"))

    def test_commission_is_zero_when_no_purchases_that_month(self):
        """مقدار رسیده = 0 must not raise (division guard), and the
        correct, safe result is 0 رather than a crash."""
        wd1 = self._wd()
        OpeningInventory.objects.create(
            tank=self.regular_tank, opening_quantity=Decimal("100"), effective_month=self.day1,
        )
        TankInventory.objects.create(tank=self.regular_tank, working_day=wd1, actual_inventory=Decimal("90"))

        rows = build_statement_rows(1405, 5)
        row = next(r for r in rows if r["tank"] == self.regular_tank)
        self.assertEqual(row["total_purchase"], Decimal("0"))
        self.assertEqual(row["commission"], Decimal("0.00"))

    def test_commission_uses_the_selected_months_own_values(self):
        """Changing the selected month must use that month's own کسری/
        مقدار رسیده, not another month's."""
        wd1 = self._wd()
        OpeningInventory.objects.create(
            tank=self.regular_tank, opening_quantity=Decimal("0"), effective_month=self.day1,
        )
        PurchaseInvoice.objects.create(
            working_day=wd1, tank=self.regular_tank, quantity=Decimal("10"), purchase_rate=Decimal("1200"),
        )
        TankInventory.objects.create(tank=self.regular_tank, working_day=wd1, actual_inventory=Decimal("5"))

        day2 = datetime.date(2026, 8, 23)  # a later Jalali month
        wd2 = DailyWorkingDay.objects.create(date=day2)
        PurchaseInvoice.objects.create(
            working_day=wd2, tank=self.regular_tank, quantity=Decimal("20"), purchase_rate=Decimal("1200"),
        )
        TankInventory.objects.create(tank=self.regular_tank, working_day=wd2, actual_inventory=Decimal("16"))

        month5_rows = build_statement_rows(1405, 5)
        month5_row = next(r for r in month5_rows if r["tank"] == self.regular_tank)
        self.assertEqual(month5_row["commission"], Decimal("5000.00"))  # (5*10000)/10

        month6_rows = build_statement_rows(1405, 6)
        month6_row = next(r for r in month6_rows if r["tank"] == self.regular_tank)
        # Not the same as month 5's -- it must be month 6's own
        # کسری/مقدار رسیده, whatever those compute to.
        self.assertNotEqual(month6_row["commission"], month5_row["commission"])
        self.assertEqual(
            month6_row["commission"],
            (month6_row["total_shortage"] * Decimal("10000") / month6_row["total_purchase"]).quantize(Decimal("0.01")),
        )

    def test_unauthorized_shortage_formula(self):
        wd1 = self._wd()
        OpeningInventory.objects.create(
            tank=self.regular_tank, opening_quantity=Decimal("1000"), effective_month=self.day1,
        )
        PurchaseInvoice.objects.create(
            working_day=wd1, tank=self.regular_tank, quantity=Decimal("450"), purchase_rate=Decimal("1200"),
        )
        # Actual below theoretical -> a shortage exists.
        TankInventory.objects.create(tank=self.regular_tank, working_day=wd1, actual_inventory=Decimal("1000"))

        rows = build_statement_rows(1405, 5)
        row = next(r for r in rows if r["tank"] == self.regular_tank)
        allowed = (Decimal("450") * Decimal("45") / Decimal("10000")).quantize(Decimal("0.01"))
        self.assertEqual(row["allowed_shortage"], allowed)
        self.assertEqual(row["unauthorized_shortage"], (row["total_shortage"] - allowed).quantize(Decimal("0.01")))

    def test_tanker_count_counts_purchase_invoices_not_liters(self):
        wd1 = self._wd()
        wd2 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 24))
        PurchaseInvoice.objects.create(working_day=wd1, tank=self.regular_tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"))
        PurchaseInvoice.objects.create(working_day=wd1, tank=self.regular_tank, quantity=Decimal("50"), purchase_rate=Decimal("1200"))
        PurchaseInvoice.objects.create(working_day=wd2, tank=self.regular_tank, quantity=Decimal("9999"), purchase_rate=Decimal("1200"))

        rows = build_statement_rows(1405, 5)
        row = next(r for r in rows if r["tank"] == self.regular_tank)
        self.assertEqual(row["tanker_count"], 3)

    def test_tanker_capacity_defaults_to_32000_and_is_independent_field(self):
        rows = build_statement_rows(1405, 5)
        for row in rows:
            self.assertEqual(row["tanker_capacity"], 32000)

    def test_digital_sales_difference_none_until_entered(self):
        rows = build_statement_rows(1405, 5)
        for row in rows:
            self.assertIsNone(row["digital_sales_difference"])

    def test_digital_sales_difference_computed_after_entry(self):
        wd1 = self._wd()
        invoice = SalesInvoice.objects.create(working_day=wd1, operator=self.user)
        NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=self.nozzle,
            previous_meter=Decimal("0"), new_meter=Decimal("1000"), test=Decimal("0"), sales_rate=Decimal("1200"),
        )
        entry = StatementEntry.objects.create(tank=self.regular_tank, year=1405, month=5, digital_sales=Decimal("900"))

        rows = build_statement_rows(1405, 5)
        row = next(r for r in rows if r["tank"] == self.regular_tank)
        self.assertEqual(row["digital_sales_difference"], row["total_sales"] - Decimal("900"))
        self.assertEqual(row["entry"].id, entry.id)


class StatementPrintContextTests(TestCase):
    """
    Renders the actual printing/statement_print.html template (the exact
    HTML source WeasyPrint converts to PDF) through
    build_statement_context(), so this verifies the PDF content itself
    without needing weasyprint installed.
    """

    def setUp(self):
        station = Station.objects.create(name="S_stmt_print", province="P", city="C")
        self.product = Product.objects.create(name="بنزین معمولی")
        Tank.objects.create(station=station, product=self.product, capacity=50000)

    def test_pdf_source_html_no_longer_has_total_received_column(self):
        from django.template.loader import render_to_string

        from apps.printing.services import build_statement_context

        context = build_statement_context(1405, 5)
        html = render_to_string("printing/statement_print.html", context)

        self.assertNotIn("جمع کل رسیده ها", html)
        self.assertIn('colspan="6"', html)
        self.assertIn("جمع کل خارج شده", html)


class StatementViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op_stmt_view", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S_stmt_view", province="P", city="C")
        self.product = Product.objects.create(name="بنزین معمولی")
        self.tank = Tank.objects.create(station=station, product=self.product, capacity=50000)
        self.client.login(username="op_stmt_view", password="testpass123")

    def test_page_loads_and_has_no_submit_button(self):
        resp = self.client.get("/statement/?year=1405&month=5")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(">نمایش<", resp.content.decode())

    def test_page_shows_both_products_and_required_column_labels(self):
        resp = self.client.get("/statement/?year=1405&month=5")
        content = resp.content.decode()
        for label in [
            "رسیده", "خارج شده", "موجودی اول ماه", "مقدار رسیده", "سرک", "جمع کل",
            "مقدار فروش", "کسری", "موجودی آخر ماه", "جمع کل خارج شده",
            "اختلاف فروش دیجیتال و مکانیکی", "پورسانت", "مقدار لیتراژ کسری غیرمجازه",
            "تعداد نفتکش", "ظرفیت نفتکش", "ورود فروش دیجیتال",
        ]:
            self.assertIn(label, content)

    def test_month_selector_offers_exactly_twelve_months(self):
        """Bug fix: {% for m in "123456789101112" %} iterates that STRING
        character by character (15 chars), producing 15 options instead
        of 12 -- now it's 12 explicit options, same fix as گزارش ماهانه
        مخازن and مقایسه سیستم مکانیکی و دیجیتال."""
        resp = self.client.get("/statement/?year=1405&month=5")
        content = resp.content.decode()
        self.assertEqual(content.count('<option value="'), 12)
        for m in range(1, 13):
            self.assertIn(f'<option value="{m}"', content)
        for m in range(13, 16):
            self.assertNotIn(f'<option value="{m}"', content)

    def test_upper_table_no_longer_has_total_received_column(self):
        """Task 1: "جمع کل رسیده ها" must be gone from the upper table.
        The secondary table's unrelated "جمع کل رسیده" column (no "ها")
        is untouched and must still be present."""
        resp = self.client.get("/statement/?year=1405&month=5")
        content = resp.content.decode()
        self.assertNotIn("جمع کل رسیده ها", content)
        self.assertIn("جمع کل رسیده", content)

    def test_print_button_present(self):
        resp = self.client.get("/statement/?year=1405&month=5")
        self.assertIn("statement/?year=1405&month=5", resp.content.decode())

    def test_digital_sales_form_is_centered(self):
        """UI fix: the form panel must be centered (margin: 0 auto), like
        the existing فاکتورهای فروش / واریزی‌ها forms, not stuck to the
        right edge."""
        entry = StatementEntry.objects.create(tank=self.tank, year=1405, month=5)
        resp = self.client.get(f"/statement/entry/{entry.id}/digital-sales/")
        self.assertIn("margin: 0 auto", resp.content.decode())

    def test_digital_sales_form_saves_and_redirects(self):
        entry = StatementEntry.objects.create(tank=self.tank, year=1405, month=5)
        resp = self.client.post(
            f"/statement/entry/{entry.id}/digital-sales/", {"digital_sales": "1234.50"},
        )
        self.assertEqual(resp.status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(entry.digital_sales, Decimal("1234.50"))

    def test_tanker_capacity_form_saves_and_redirects(self):
        entry = StatementEntry.objects.create(tank=self.tank, year=1405, month=5)
        resp = self.client.post(
            f"/statement/entry/{entry.id}/tanker-capacity/", {"tanker_capacity": "40000"},
        )
        self.assertEqual(resp.status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(entry.tanker_capacity, 40000)

    def test_decade_like_label_not_hardcoded_for_products(self):
        # Sanity: adding a differently-named third product must not break
        # the page (product names are never hardcoded).
        Tank.objects.create(station=self.tank.station, product=Product.objects.create(name="گازوئیل"), capacity=10000)
        resp = self.client.get("/statement/?year=1405&month=5")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "گازوئیل")
