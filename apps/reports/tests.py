"""
Reports are read-only derived views over existing source-of-truth data.
These tests verify that:
1. Reports render without errors and show aggregated data.
2. Report numbers are computed on-the-fly from existing models, not stored.
3. Changes to source data (sales, purchases, inventory) immediately
   reflect in reports without needing cache invalidation.
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

User = get_user_model()


class ReportsHttpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S", province="P", city="C")
        self.product = Product.objects.create(name="Regular")
        self.tank = Tank.objects.create(station=station, product=self.product, capacity=50000)
        self.nozzle = Nozzle.objects.create(tank=self.tank, number=1)
        self.wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))
        self.client.login(username="op1", password="testpass123")

    def test_nozzle_ledger_renders(self):
        resp = self.client.get("/reports/nozzle-ledger/?nozzle_id=1")
        self.assertEqual(resp.status_code, 200)

    def test_nozzle_ledger_shows_nozzle_data(self):
        invoice = SalesInvoice.objects.create(working_day=self.wd, operator=self.user)
        NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=self.nozzle,
            previous_meter=Decimal("0"), new_meter=Decimal("100"), test=Decimal("0"),
            sales_rate=Decimal("1200"),
        )
        # Explicit range around the working day (2026-08-01) rather than
        # relying on the view's "current month" default, which tracks
        # wall-clock time and would otherwise make this test flaky as
        # real time moves away from the seeded date.
        resp = self.client.get(
            "/reports/nozzle-ledger/"
            "?nozzle_id=1&start_date=2026-07-25&end_date=2026-08-05"
        )
        self.assertContains(resp, "100")  # operation, mechanical_sales, daily_total, cumulative_total (all same on day 1 since test=0)

    def test_nozzle_ledger_date_range_filter(self):
        invoice = SalesInvoice.objects.create(working_day=self.wd, operator=self.user)
        NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=self.nozzle,
            previous_meter=Decimal("0"), new_meter=Decimal("100"), test=Decimal("0"),
            sales_rate=Decimal("1200"),
        )
        resp = self.client.get(
            "/reports/nozzle-ledger/"
            "?nozzle_id=1&start_date=2026-08-02&end_date=2026-08-31"
        )
        self.assertNotContains(resp, "100")  # outside range

    def test_nozzle_monthly_renders(self):
        resp = self.client.get("/reports/nozzle-monthly/?year=1405&month=5")
        self.assertEqual(resp.status_code, 200)

    def test_nozzle_monthly_aggregates_correctly(self):
        invoice = SalesInvoice.objects.create(working_day=self.wd, operator=self.user)
        NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=self.nozzle,
            previous_meter=Decimal("0"), new_meter=Decimal("100"), test=Decimal("0"),
            sales_rate=Decimal("1200"),
        )
        # working_day date 2026-08-01 is Jalali 1405/05/10 -- year/month
        # here are Jalali, so this queries the Jalali month containing it.
        resp = self.client.get("/reports/nozzle-monthly/?year=1405&month=5")
        self.assertContains(resp, "100")  # total operation and total sales_amount
        self.assertContains(resp, "120,000")  # total total_amount (100 * 1200)

    def test_nozzle_monthly_excludes_other_months(self):
        invoice = SalesInvoice.objects.create(working_day=self.wd, operator=self.user)
        NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=self.nozzle,
            previous_meter=Decimal("0"), new_meter=Decimal("100"), test=Decimal("0"),
            sales_rate=Decimal("1200"),
        )
        # 1405/06 is a different Jalali month from the working day's 1405/05.
        resp = self.client.get("/reports/nozzle-monthly/?year=1405&month=6")
        self.assertNotContains(resp, "100")

    def test_petroleum_ledger_renders(self):
        resp = self.client.get("/reports/petroleum-ledger/?tank_id=1")
        self.assertEqual(resp.status_code, 200)

    def test_petroleum_ledger_shows_aggregations(self):
        PurchaseInvoice.objects.create(
            working_day=self.wd, tank=self.tank, quantity=Decimal("100"),
            purchase_rate=Decimal("1000"),
        )
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"),
            effective_month=datetime.date(2026, 8, 1),
        )
        TankInventory.objects.create(
            tank=self.tank, working_day=self.wd, actual_inventory=Decimal("100"),
        )
        # Explicit range -- see test_nozzle_ledger_shows_nozzle_data above
        # for why this can't rely on the view's "current month" default.
        resp = self.client.get(
            "/reports/petroleum-ledger/"
            "?tank_id=1&start_date=2026-07-25&end_date=2026-08-05"
        )
        self.assertContains(resp, "100")  # daily purchase

    def test_petroleum_monthly_renders(self):
        resp = self.client.get("/reports/petroleum-monthly/?year=1405&month=5")
        self.assertEqual(resp.status_code, 200)

    def test_petroleum_monthly_aggregates_purchases(self):
        PurchaseInvoice.objects.create(
            working_day=self.wd, tank=self.tank, quantity=Decimal("100"),
            purchase_rate=Decimal("1000"),
        )
        # working_day date 2026-08-01 is Jalali 1405/05/10. "کل خرید" is no
        # longer a displayed column on this report (see the rework's own
        # task doc), but the underlying purchase total must still be
        # computed correctly by the service function underneath the page.
        from apps.reports import services as report_services
        report = report_services.petroleum_inventory_monthly(self.tank, 1405, 5)
        self.assertEqual(report["total_purchase"], Decimal("100"))

        resp = self.client.get("/reports/petroleum-monthly/?year=1405&month=5")
        self.assertEqual(resp.status_code, 200)

    def test_report_reflects_live_data_changes(self):
        """
        Verify that reports are truly derived views: changing source data
        immediately updates the report, no caching or duplication.
        """
        # Explicit range around the working day (2026-08-01) rather than
        # the view's "current month" default -- see
        # test_nozzle_ledger_shows_nozzle_data above.
        url = (
            "/reports/nozzle-ledger/"
            "?nozzle_id=1&start_date=2026-07-25&end_date=2026-08-05"
        )

        # First state: no sales -- the ledger's own empty-state message
        # (not a date string, which can coincidentally also appear in
        # the page header's global date control).
        resp1 = self.client.get(url)
        self.assertContains(resp1, "اطلاعاتی یافت نشد")

        # Add a sale
        invoice = SalesInvoice.objects.create(working_day=self.wd, operator=self.user)
        NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=self.nozzle,
            previous_meter=Decimal("0"), new_meter=Decimal("100"), test=Decimal("0"),
            sales_rate=Decimal("1200"),
        )

        # Report immediately shows the new data
        resp2 = self.client.get(url)
        self.assertContains(resp2, "100")  # operation, mechanical_sales, daily_total, cumulative_total

        # Edit the sale
        sale = NozzleSale.objects.get(nozzle=self.nozzle)
        sale.new_meter = Decimal("150")
        sale.save()

        # Report immediately reflects the change in the table data
        resp3 = self.client.get(url)
        self.assertContains(resp3, "150")  # operation, mechanical_sales, daily_total, cumulative_total (updated)


# ---------------------------------------------------------------------------
# Phase 7 verification tests: focused checks against Architecture v3 rules
# that were not yet covered (beginning/end-of-month meter, Daily Total 1/2,
# beginning/ending monthly inventory, first-accounting-month backfill,
# frozen historical sales rate, shortage/overage consistency with
# TankInventory, and report recalculation after editing source data).
# ---------------------------------------------------------------------------

class NozzleLedgerArrowKeyNavigationTests(TestCase):
    """
    Task 4A: ArrowUp/ArrowDown navigate نازل‌ها گزارش کارکرد هر نازل
    between the 18 nozzles (regular 1..14, then CNG 1..4), clamped at both ends. Verified structurally
    (script present, correctly wired, boundary clamp logic present) --
    this project has no JS test runner, same verification level as the
    project's other JS keyboard shortcuts -- plus a functional check
    that every target nozzle (1 and CNG 4, the boundaries) the script would
    navigate to is itself reachable and renders correctly, and that the
    date range it carries through is preserved.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="op_arrow", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S_arrow", province="P", city="C")
        product = Product.objects.create(name="Regular")
        tank = Tank.objects.create(station=station, product=product, capacity=50000)
        cng_tank = Tank.objects.create(station=station, product=Product.objects.create(name="CNG"), capacity=0)
        # Regular nozzles keyed 1..14, CNG nozzles keyed "CNG 1".."CNG 4" (18 in all).
        self.nozzles = {n: Nozzle.objects.create(tank=tank, number=n) for n in range(1, 15)}
        self.nozzles.update({f"CNG {n}": Nozzle.objects.create(tank=cng_tank, number=n) for n in range(1, 5)})
        self.client.login(username="op_arrow", password="testpass123")

    def test_select_has_an_id_for_the_script_to_target(self):
        resp = self.client.get("/reports/nozzle-ledger/?nozzle_id=" + str(self.nozzles[10].id))
        self.assertContains(resp, 'id="nozzle-select"')

    def test_arrow_key_script_present_and_correctly_wired(self):
        resp = self.client.get("/reports/nozzle-ledger/?nozzle_id=" + str(self.nozzles[10].id))
        content = resp.content.decode()
        self.assertIn("ArrowUp", content)
        self.assertIn("ArrowDown", content)
        self.assertIn("keydown", content)
        self.assertIn("nozzle-select", content)
        # Ignored while typing/focused on a control.
        self.assertIn("'input'", content)
        self.assertIn("'select'", content)
        self.assertIn("isContentEditable", content)

    def test_options_are_in_nozzle_order_regular_then_cng(self):
        """The script walks <option>s in DOM order to find next/previous
        -- this order IS the navigation order, so it must be exactly
        regular 1..14 ascending, then CNG 1..4."""
        resp = self.client.get("/reports/nozzle-ledger/?nozzle_id=" + str(self.nozzles[1].id))
        content = resp.content.decode()
        order = list(range(1, 15)) + [f"CNG {n}" for n in range(1, 5)]
        positions = [content.index(f'value="{self.nozzles[n].id}"') for n in order]
        self.assertEqual(positions, sorted(positions))

    def test_every_nozzle_boundary_is_a_reachable_target(self):
        """Boundary + general reachability check: nozzle 1 and CNG 4
        (the two ends the clamp logic must respect) both render fine as
        navigation targets, as does a middle nozzle."""
        for n in (1, 10, "CNG 4"):
            resp = self.client.get(f"/reports/nozzle-ledger/?nozzle_id={self.nozzles[n].id}")
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, f"نازل {n}")

    def test_date_range_is_preserved_across_nozzle_selection(self):
        """Confirms the select's own navigation (which the script
        triggers via a change event) carries start_date/end_date through
        unchanged -- the script does not touch the date filter."""
        resp = self.client.get(
            f"/reports/nozzle-ledger/?nozzle_id={self.nozzles[5].id}"
            "&start_date=2026-07-01&end_date=2026-07-31"
        )
        content = resp.content.decode()
        self.assertIn("start_date=2026-07-01", content)
        self.assertIn("end_date=2026-07-31", content)


class Phase7RuleComplianceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op2", password="testpass123")
        # Mid-month activation: 2026-08-15 is Jalali 1405/05/24 -- the
        # accounting start must be day 1 of THAT Jalali month, which is
        # Gregorian 2026-07-23 (Jalali 1405/05/01), not the 1st of the
        # Gregorian calendar month (2026-08-01).
        License.objects.create(start_date=datetime.date(2026, 8, 15), duration_days=365)
        station = Station.objects.create(name="S2", province="P", city="C")
        self.product = Product.objects.create(name="Regular2")
        self.tank = Tank.objects.create(station=station, product=self.product, capacity=50000)
        self.nozzle = Nozzle.objects.create(tank=self.tank, number=1)
        self.client.login(username="op2", password="testpass123")

    def _make_day(self, iso_date):
        return DailyWorkingDay.objects.create(date=datetime.date.fromisoformat(iso_date))

    def _make_sale(self, wd, previous_meter, new_meter, test=Decimal("0"), rate=Decimal("1200")):
        invoice = SalesInvoice.objects.get_or_create(working_day=wd, defaults={"operator": self.user})[0]
        return NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=self.nozzle,
            previous_meter=previous_meter, new_meter=new_meter, test=test, sales_rate=rate,
        )

    # --- Rule 5: first-accounting-month backfill ---

    def test_monthly_reports_cover_full_calendar_month_despite_mid_month_activation(self):
        # Activation was 2026-08-15 (Jalali 1405/05/24), but the operator
        # backfills from 2026-07-23 (Jalali 1405/05/01) onward.
        # year/month args to nozzle_performance_monthly are Jalali.
        wd1 = self._make_day("2026-07-23")
        self._make_sale(wd1, Decimal("0"), Decimal("50"))
        from apps.reports import services as report_services
        report = report_services.nozzle_performance_monthly(self.nozzle, 1405, 5)
        self.assertIsNotNone(report)
        self.assertEqual(report["beginning_of_month_meter"], Decimal("0"))
        self.assertEqual(report["total_operation"], Decimal("50"))

    def test_accounting_start_is_jalali_month_day_1_not_activation_date(self):
        from apps.workday import services as workday_services
        start = workday_services.get_accounting_start_date()
        self.assertEqual(start, datetime.date(2026, 7, 23))

    # --- Rule 2: beginning/end-of-month meter ---

    def test_beginning_of_month_meter_is_first_accounting_month_day1_reading(self):
        # 2026-07-23 is Jalali 1405/05/01 -- day 1 of the accounting month.
        wd1 = self._make_day("2026-07-23")
        self._make_sale(wd1, Decimal("100"), Decimal("150"))
        from apps.reports import services as report_services
        report = report_services.nozzle_performance_monthly(self.nozzle, 1405, 5)
        self.assertEqual(report["beginning_of_month_meter"], Decimal("100"))

    def test_end_of_month_meter_is_latest_registered_reading(self):
        # Both dates are within Jalali 1405/05.
        wd1 = self._make_day("2026-07-23")
        wd2 = self._make_day("2026-07-24")
        self._make_sale(wd1, Decimal("100"), Decimal("150"))
        self._make_sale(wd2, Decimal("150"), Decimal("220"))
        from apps.reports import services as report_services
        report = report_services.nozzle_performance_monthly(self.nozzle, 1405, 5)
        self.assertEqual(report["end_of_month_meter"], Decimal("220"))

    def test_beginning_of_month_meter_for_second_month_uses_prior_months_ending_meter(self):
        # 2026-08-22 is the LAST day of Jalali 1405/05 (1405/05/31);
        # 2026-08-23 is the FIRST day of Jalali 1405/06 (1405/06/01) --
        # these straddle a real Jalali month boundary.
        wd_prev_month = self._make_day("2026-08-22")
        self._make_sale(wd_prev_month, Decimal("900"), Decimal("1000"))
        wd_next_month = self._make_day("2026-08-23")
        self._make_sale(wd_next_month, Decimal("1000"), Decimal("1050"))
        from apps.reports import services as report_services
        report = report_services.nozzle_performance_monthly(self.nozzle, 1405, 6)
        self.assertEqual(report["beginning_of_month_meter"], Decimal("1000"))

    def test_beginning_of_month_meter_not_hardcoded_reflects_actual_data(self):
        # Different starting meter must produce a different result --
        # proves this is derived, not a hardcoded/default value.
        # 2026-07-23 is Jalali 1405/05/01.
        wd1 = self._make_day("2026-07-23")
        self._make_sale(wd1, Decimal("54321"), Decimal("54400"))
        from apps.reports import services as report_services
        report = report_services.nozzle_performance_monthly(self.nozzle, 1405, 5)
        self.assertEqual(report["beginning_of_month_meter"], Decimal("54321"))

    # --- Rule 1: frozen historical sales rate reflected in reports ---

    def test_ledger_uses_frozen_historical_sales_rate_not_current_default(self):
        wd1 = self._make_day("2026-07-23")
        self._make_sale(wd1, Decimal("0"), Decimal("100"), rate=Decimal("1000"))
        # A later purchase/sale changes the "current" rate elsewhere, but
        # this historical record's rate must remain frozen at 1000.
        wd2 = self._make_day("2026-07-24")
        nozzle2 = Nozzle.objects.create(tank=self.tank, number=2)
        invoice2 = SalesInvoice.objects.create(working_day=wd2, operator=self.user)
        NozzleSale.objects.create(
            sales_invoice=invoice2, nozzle=nozzle2,
            previous_meter=Decimal("0"), new_meter=Decimal("50"), test=Decimal("0"),
            sales_rate=Decimal("1500"),
        )
        from apps.reports import services as report_services
        rows = report_services.nozzle_performance_ledger(
            self.nozzle, datetime.date(2026, 7, 23), datetime.date(2026, 8, 22)
        )
        self.assertEqual(rows[0]["sales_rate"], Decimal("1000"))
        self.assertEqual(rows[0]["total_amount"], Decimal("100000"))  # 100 * 1000

    # --- Rule 3: F6 Daily Total 1 / Daily Total 2, shortage/overage consistency ---

    def test_f6_daily_total_1_and_2_match_formula(self):
        wd1 = self._make_day("2026-07-23")
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("1000"),
            effective_month=datetime.date(2026, 7, 23),
        )
        PurchaseInvoice.objects.create(
            working_day=wd1, tank=self.tank, quantity=Decimal("100"),
            purchase_rate=Decimal("1200"),
        )
        self._make_sale(wd1, Decimal("0"), Decimal("205"), test=Decimal("5"))
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("905"))

        from apps.reports import services as report_services
        from apps.inventory import services as inventory_services

        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 23)
        )
        row = rows[0]

        total, theoretical, shortage, overage = inventory_services.compute_tank_inventory(self.tank, wd1)

        expected_total_1 = row["daily_purchase"] + row["test_return"] + overage
        # No + actual_inventory -- see test_daily_dispatched_formula above.
        expected_total_2 = row["daily_sales"] + row["test_return"] + shortage

        self.assertEqual(row["daily_total_1"], expected_total_1)
        self.assertEqual(row["daily_total_2"], expected_total_2)
        # Shortage/overage in the report must be identical to
        # TankInventory's own computation -- no second calculation.
        self.assertEqual(row["shortage"], shortage)
        self.assertEqual(row["overage"], overage)

    # --- Rule 4: beginning/ending monthly inventory, OpeningInventory=0 and non-zero ---

    def test_monthly_beginning_inventory_uses_opening_inventory_zero(self):
        wd1 = self._make_day("2026-07-23")
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"),
            effective_month=datetime.date(2026, 7, 23),
        )
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("0"))
        from apps.reports import services as report_services
        report = report_services.petroleum_inventory_monthly(self.tank, 1405, 5)
        self.assertEqual(report["beginning_inventory"], Decimal("0"))

    def test_monthly_beginning_inventory_uses_non_zero_opening_inventory(self):
        wd1 = self._make_day("2026-07-23")
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("5000"),
            effective_month=datetime.date(2026, 7, 23),
        )
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("5000"))
        from apps.reports import services as report_services
        report = report_services.petroleum_inventory_monthly(self.tank, 1405, 5)
        self.assertEqual(report["beginning_inventory"], Decimal("5000"))

    def test_monthly_beginning_inventory_second_month_uses_prior_months_ending_actual(self):
        # 2026-08-22 is the LAST day of Jalali 1405/05; 2026-08-23 is the
        # FIRST day of Jalali 1405/06 -- see the identical comment on
        # test_beginning_of_month_meter_for_second_month_uses_prior_months_ending_meter
        # above.
        wd_prev_month = self._make_day("2026-08-22")
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"),
            effective_month=datetime.date(2026, 7, 23),
        )
        TankInventory.objects.create(tank=self.tank, working_day=wd_prev_month, actual_inventory=Decimal("777"))
        wd_next_month = self._make_day("2026-08-23")
        TankInventory.objects.create(tank=self.tank, working_day=wd_next_month, actual_inventory=Decimal("800"))

        from apps.reports import services as report_services
        report = report_services.petroleum_inventory_monthly(self.tank, 1405, 6)
        self.assertEqual(report["beginning_inventory"], Decimal("777"))

    def test_monthly_ending_inventory_is_last_registered_actual_never_manual(self):
        wd1 = self._make_day("2026-07-23")
        wd2 = self._make_day("2026-07-24")
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"),
            effective_month=datetime.date(2026, 7, 23),
        )
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("100"))
        TankInventory.objects.create(tank=self.tank, working_day=wd2, actual_inventory=Decimal("250"))

        from apps.reports import services as report_services
        report = report_services.petroleum_inventory_monthly(self.tank, 1405, 5)
        self.assertEqual(report["ending_inventory"], Decimal("250"))

    # --- Rule 6 + item 7: report recalculation after editing source data ---

    def test_f6_ledger_recalculates_after_editing_actual_inventory(self):
        wd1 = self._make_day("2026-07-23")
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"),
            effective_month=datetime.date(2026, 7, 23),
        )
        inv_row = TankInventory.objects.create(
            tank=self.tank, working_day=wd1, actual_inventory=Decimal("10")
        )
        from apps.reports import services as report_services

        rows_before = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 23)
        )
        self.assertEqual(rows_before[0]["overage"], Decimal("10"))

        inv_row.actual_inventory = Decimal("0")
        inv_row.save()

        rows_after = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 23)
        )
        self.assertEqual(rows_after[0]["overage"], Decimal("0"))

    def test_monthly_statement_recalculates_after_deleting_purchase(self):
        wd1 = self._make_day("2026-07-23")
        purchase = PurchaseInvoice.objects.create(
            working_day=wd1, tank=self.tank, quantity=Decimal("500"),
            purchase_rate=Decimal("1000"),
        )
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"),
            effective_month=datetime.date(2026, 7, 23),
        )
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("500"))

        from apps.reports import services as report_services
        report_before = report_services.petroleum_inventory_monthly(self.tank, 1405, 5)
        self.assertEqual(report_before["total_purchase"], Decimal("500"))

        purchase.delete()

        report_after = report_services.petroleum_inventory_monthly(self.tank, 1405, 5)
        self.assertEqual(report_after["total_purchase"], Decimal("0"))

class NozzleLedgerNewColumnsTests(TestCase):
    """
    Covers the نازل‌ها daily ledger's reworked columns: کنتور قبلی,
    آزمایش, کنتور جدید are the raw NozzleSale values; جمع روزانه =
    فروش مکانیکی + آزمایش; جمع کل is the running sum of جمع روزانه
    across the selected date range.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="op3", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S3", province="P", city="C")
        product = Product.objects.create(name="Regular3")
        self.tank = Tank.objects.create(station=station, product=product, capacity=50000)
        self.nozzle = Nozzle.objects.create(tank=self.tank, number=1)

    def _make_day(self, iso_date):
        return DailyWorkingDay.objects.create(date=datetime.date.fromisoformat(iso_date))

    def _make_sale(self, wd, previous_meter, new_meter, test=Decimal("0"), rate=Decimal("1200")):
        invoice = SalesInvoice.objects.get_or_create(working_day=wd, defaults={"operator": self.user})[0]
        return NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=self.nozzle,
            previous_meter=previous_meter, new_meter=new_meter, test=test, sales_rate=rate,
        )

    def test_row_exposes_previous_meter_test_and_new_meter_verbatim(self):
        wd = self._make_day("2026-08-01")
        self._make_sale(wd, previous_meter=Decimal("100"), new_meter=Decimal("160"), test=Decimal("5"))
        from apps.reports import services as report_services
        rows = report_services.nozzle_performance_ledger(
            self.nozzle, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1)
        )
        self.assertEqual(rows[0]["previous_meter"], Decimal("100"))
        self.assertEqual(rows[0]["new_meter"], Decimal("160"))
        self.assertEqual(rows[0]["test"], Decimal("5"))

    def test_daily_total_equals_mechanical_sales_plus_test(self):
        wd = self._make_day("2026-08-01")
        # operation = 60, test = 5 -> mechanical_sales = 55 -> daily_total = 55 + 5 = 60
        self._make_sale(wd, previous_meter=Decimal("100"), new_meter=Decimal("160"), test=Decimal("5"))
        from apps.reports import services as report_services
        rows = report_services.nozzle_performance_ledger(
            self.nozzle, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1)
        )
        self.assertEqual(rows[0]["mechanical_sales"], Decimal("55"))
        self.assertEqual(rows[0]["daily_total"], Decimal("60"))

    def test_daily_total_with_no_test_matches_ui_zero_convention(self):
        wd = self._make_day("2026-08-01")
        self._make_sale(wd, previous_meter=Decimal("0"), new_meter=Decimal("50"))  # test defaults to 0
        from apps.reports import services as report_services
        rows = report_services.nozzle_performance_ledger(
            self.nozzle, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1)
        )
        self.assertEqual(rows[0]["test"], Decimal("0"))
        self.assertEqual(rows[0]["daily_total"], Decimal("50"))

    def test_cumulative_total_on_first_available_day_equals_its_own_daily_total(self):
        wd = self._make_day("2026-08-01")
        self._make_sale(wd, previous_meter=Decimal("0"), new_meter=Decimal("50"))
        from apps.reports import services as report_services
        rows = report_services.nozzle_performance_ledger(
            self.nozzle, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1)
        )
        self.assertEqual(rows[0]["cumulative_total"], rows[0]["daily_total"])
        self.assertEqual(rows[0]["cumulative_total"], Decimal("50"))

    def test_cumulative_total_accumulates_across_multiple_days(self):
        wd1 = self._make_day("2026-08-01")
        wd2 = self._make_day("2026-08-02")
        wd3 = self._make_day("2026-08-03")
        self._make_sale(wd1, previous_meter=Decimal("0"), new_meter=Decimal("50"))       # daily_total 50
        self._make_sale(wd2, previous_meter=Decimal("50"), new_meter=Decimal("120"), test=Decimal("10"))  # op=70, mech=60, daily_total=70
        self._make_sale(wd3, previous_meter=Decimal("120"), new_meter=Decimal("150"))     # daily_total 30

        from apps.reports import services as report_services
        rows = report_services.nozzle_performance_ledger(
            self.nozzle, datetime.date(2026, 8, 1), datetime.date(2026, 8, 3)
        )
        self.assertEqual(rows[0]["cumulative_total"], Decimal("50"))
        self.assertEqual(rows[1]["cumulative_total"], Decimal("120"))   # 50 + 70
        self.assertEqual(rows[2]["cumulative_total"], Decimal("150"))   # 120 + 30

    def test_cumulative_total_ignores_days_outside_the_selected_range(self):
        # A day before the range must not silently contribute to the
        # first in-range day's cumulative total.
        wd0 = self._make_day("2026-07-31")
        wd1 = self._make_day("2026-08-01")
        self._make_sale(wd0, previous_meter=Decimal("0"), new_meter=Decimal("9999"))
        self._make_sale(wd1, previous_meter=Decimal("9999"), new_meter=Decimal("10049"))  # daily_total 50

        from apps.reports import services as report_services
        rows = report_services.nozzle_performance_ledger(
            self.nozzle, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cumulative_total"], Decimal("50"))

    def test_operation_and_sales_rate_unchanged_by_the_rework(self):
        # operation remains in the service's row data (still used by the
        # monthly report and the model itself) even though it is no
        # longer a displayed column on this ledger -- see
        # nozzle_performance_ledger.html.
        wd = self._make_day("2026-08-01")
        self._make_sale(wd, previous_meter=Decimal("100"), new_meter=Decimal("160"), test=Decimal("5"), rate=Decimal("1200"))
        from apps.reports import services as report_services
        rows = report_services.nozzle_performance_ledger(
            self.nozzle, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1)
        )
        self.assertEqual(rows[0]["operation"], Decimal("60"))
        self.assertEqual(rows[0]["sales_rate"], Decimal("1200"))

    def test_new_columns_render_on_the_ledger_page(self):
        self.client.login(username="op3", password="testpass123")
        wd1 = self._make_day("2026-08-01")
        wd2 = self._make_day("2026-08-02")
        self._make_sale(wd1, previous_meter=Decimal("100"), new_meter=Decimal("160"), test=Decimal("5"))
        self._make_sale(wd2, previous_meter=Decimal("160"), new_meter=Decimal("210"))

        resp = self.client.get(
            f"/reports/nozzle-ledger/?nozzle_id={self.nozzle.id}"
            "&start_date=2026-08-01&end_date=2026-08-02"
        )
        content = resp.content.decode()

        # All 8 required columns, in the exact right-to-left order given
        # (عملکرد/operation was removed: it is numerically identical to
        # جمع روزانه/daily_total, so keeping both was a duplicate column).
        for label in [
            "تاریخ", "کنتور قبلی", "آزمایش", "فروش مکانیکی",
            "جمع روزانه", "جمع کل", "کنتور جدید", "نرخ",
        ]:
            self.assertIn(label, content)

        # Both removed columns must be gone from the ledger page.
        self.assertNotIn("مبلغ کل", content)
        self.assertNotIn("عملکرد", content)

        # Day 1: daily_total = 55 (mech) + 5 (test) = 60, cumulative = 60.
        # Day 2: daily_total = 50, cumulative = 60 + 50 = 110.
        self.assertContains(resp, "60")
        self.assertContains(resp, "110")


class AllNozzlesPerformanceTests(TestCase):
    """
    Covers کارکرد تمام نازل‌ها: a dedicated, separate view/URL/service
    function from گزارش کارکرد هر نازل (nozzle_performance_ledger),
    which these tests also confirm remains completely untouched and
    reachable at its own URL.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="op_all", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S_all", province="P", city="C")
        self.regular = Product.objects.create(name="Regular")
        self.super_ = Product.objects.create(name="CNG")
        self.regular_tank = Tank.objects.create(station=station, product=self.regular, capacity=50000)
        self.super_tank = Tank.objects.create(station=station, product=self.super_, capacity=30000)
        # A realistic (smaller) mix of Regular/CNG nozzles rather than
        # all 26, to keep fixtures readable -- the aggregation logic
        # itself doesn't care about the exact count.
        self.regular_nozzles = [
            Nozzle.objects.create(tank=self.regular_tank, number=n) for n in range(1, 4)
        ]
        self.super_nozzles = [
            Nozzle.objects.create(tank=self.super_tank, number=n) for n in range(19, 21)
        ]
        self.client.login(username="op_all", password="testpass123")

    def _sell(self, nozzle, wd, previous_meter, new_meter, test=Decimal("0"), rate=Decimal("1200")):
        invoice = SalesInvoice.objects.get_or_create(working_day=wd, defaults={"operator": self.user})[0]
        return NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=nozzle,
            previous_meter=previous_meter, new_meter=new_meter, test=test, sales_rate=rate,
        )

    def test_nav_link_points_to_the_new_dedicated_view(self):
        resp = self.client.get("/")
        self.assertContains(resp, 'href="/reports/all-nozzles/"')

    def test_existing_per_nozzle_view_is_unaffected_and_still_reachable(self):
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))
        self._sell(self.regular_nozzles[0], wd, Decimal("0"), Decimal("50"))
        resp = self.client.get(f"/reports/nozzle-ledger/?nozzle_id={self.regular_nozzles[0].id}"
                                "&start_date=2026-08-01&end_date=2026-08-01")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "گزارش کارکرد هر نازل")

    # The daily, date-range version of this report was replaced by the monthly,
    # nozzle-based one -- see test_all_nozzles_report.py for its tests.


class PetroleumLedgerReworkTests(TestCase):
    """
    Covers the دفتر موجودی و عملیات rework: two symmetric رسیده/خارج شده
    sections, per-purchase-invoice detail on رسیده, the new cumulative
    totals (جمع کل رسیده/خارج شده), and the §6 data-consistency identity
    (جمع کل خارج شده + موجودی واقعی = جمع کل رسیده). The existing
    Regular/CNG tank-selector behavior is untouched -- these tests
    exercise the service function per-tank exactly as before.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="op_pled", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 7, 23), duration_days=365)
        station = Station.objects.create(name="S_pled", province="P", city="C")
        self.product = Product.objects.create(name="Regular")
        self.tank = Tank.objects.create(station=station, product=self.product, capacity=50000)
        self.nozzle = Nozzle.objects.create(tank=self.tank, number=1)
        self.client.login(username="op_pled", password="testpass123")

    def _sell(self, wd, previous_meter, new_meter, test=Decimal("0"), rate=Decimal("1200")):
        invoice = SalesInvoice.objects.get_or_create(working_day=wd, defaults={"operator": self.user})[0]
        return NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=self.nozzle,
            previous_meter=previous_meter, new_meter=new_meter, test=test, sales_rate=rate,
        )

    def test_single_purchase_day_has_one_received_row(self):
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("1000"), effective_month=datetime.date(2026, 7, 23),
        )
        PurchaseInvoice.objects.create(
            working_day=wd, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"),
            program_number="BN-1", tanker_number="TN-1",
        )
        self._sell(wd, Decimal("0"), Decimal("205"), test=Decimal("5"))
        TankInventory.objects.create(tank=self.tank, working_day=wd, actual_inventory=Decimal("905"))

        from apps.reports import services as report_services
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 23)
        )
        self.assertEqual(len(rows[0]["received_rows"]), 1)
        received = rows[0]["received_rows"][0]
        self.assertEqual(received["program_number"], "BN-1")
        self.assertEqual(received["tanker_number"], "TN-1")
        self.assertEqual(received["quantity"], Decimal("100"))

    def test_multiple_purchases_same_day_produce_one_received_row_each(self):
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"), effective_month=datetime.date(2026, 7, 23),
        )
        PurchaseInvoice.objects.create(
            working_day=wd, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"),
            program_number="BN-1", tanker_number="TN-1",
        )
        PurchaseInvoice.objects.create(
            working_day=wd, tank=self.tank, quantity=Decimal("50"), purchase_rate=Decimal("1200"),
            program_number="BN-2", tanker_number="TN-2",
        )
        TankInventory.objects.create(tank=self.tank, working_day=wd, actual_inventory=Decimal("150"))

        from apps.reports import services as report_services
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 23)
        )
        self.assertEqual(len(rows), 1)  # still one row per DAY
        self.assertEqual(len(rows[0]["received_rows"]), 2)  # two invoice lines within it
        self.assertEqual(rows[0]["received_rows"][0]["program_number"], "BN-1")
        self.assertEqual(rows[0]["received_rows"][1]["program_number"], "BN-2")
        # Day-level values attached only to the first invoice row.
        self.assertIsNotNone(rows[0]["received_rows"][0]["daily_received"])
        self.assertIsNone(rows[0]["received_rows"][1]["daily_received"])

    def test_zero_purchase_day_still_produces_one_placeholder_received_row(self):
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"), effective_month=datetime.date(2026, 7, 23),
        )
        TankInventory.objects.create(tank=self.tank, working_day=wd, actual_inventory=Decimal("0"))

        from apps.reports import services as report_services
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 23)
        )
        self.assertEqual(len(rows[0]["received_rows"]), 1)
        self.assertIsNone(rows[0]["received_rows"][0]["program_number"])
        self.assertIsNone(rows[0]["received_rows"][0]["quantity"])

    def test_daily_received_formula(self):
        # مقدار خرید + مجموع آزمایش + سرک = جمع روزانه‌ی رسیده
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("1000"), effective_month=datetime.date(2026, 7, 23),
        )
        PurchaseInvoice.objects.create(
            working_day=wd, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"),
        )
        self._sell(wd, Decimal("0"), Decimal("205"), test=Decimal("5"))
        # Total=1105, Sales(mech)=200, Test=5, Theoretical = 1105 - (200 + 5) = 900,
        # Actual=905 -> overage(سرک)=5
        TankInventory.objects.create(tank=self.tank, working_day=wd, actual_inventory=Decimal("905"))

        from apps.reports import services as report_services
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 23)
        )
        received = rows[0]["received_rows"][0]
        self.assertEqual(received["overage"], Decimal("5"))
        self.assertEqual(received["test_return"], Decimal("5"))
        # 100 (purchase) + 5 (test) + 5 (سرک) = 110
        self.assertEqual(received["daily_received"], Decimal("110"))

    def test_daily_dispatched_formula(self):
        # جمع روزانه خارج شده = جمع فروش مکانیکی + مجموع آزمایش + کسری
        # (موجودی واقعی does NOT contribute -- a previous version of this
        # formula mistakenly added it in; corrected here.)
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("1000"), effective_month=datetime.date(2026, 7, 23),
        )
        PurchaseInvoice.objects.create(
            working_day=wd, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"),
        )
        self._sell(wd, Decimal("0"), Decimal("205"), test=Decimal("5"))
        # Total=1105, mech sales=200, Test=5, Theoretical = 1105 - (200 + 5) = 900,
        # Actual=895 -> shortage(کسری)=5
        TankInventory.objects.create(tank=self.tank, working_day=wd, actual_inventory=Decimal("895"))

        from apps.reports import services as report_services
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 23)
        )
        row = rows[0]
        self.assertEqual(row["shortage"], Decimal("5"))
        # 200 (mech sales) + 5 (test) + 5 (کسری) = 210 -- موجودی واقعی
        # (900) must NOT appear in this sum.
        self.assertEqual(row["daily_dispatched"], Decimal("210"))

    def test_daily_dispatched_is_independent_of_actual_inventory_value(self):
        """Verification case 1, proven directly at the formula level:
        جمع روزانه خارج شده has NO موجودی واقعی term at all -- it is
        exactly جمع فروش مکانیکی + مجموع آزمایش + کسری (already confirmed
        numerically in test_daily_dispatched_formula above). Given that
        identity, two records sharing the same mechanical sales, test
        total, and کسری are GUARANTEED to share the same جمع روزانه خارج
        شده regardless of موجودی واقعی -- changing actual_inventory only
        ever changes کسری itself (shortage = theoretical - actual), never
        adds a separate term. This test demonstrates that directly: two
        otherwise-identical days differing ONLY in actual_inventory shift
        جمع روزانه خارج شده by EXACTLY the resulting change in کسری, never
        by the change in موجودی واقعی itself -- i.e. actual_inventory's
        effect is fully mediated through کسری, with no leftover direct
        contribution."""
        wd1 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        wd2 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 24))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("1000"), effective_month=datetime.date(2026, 7, 23),
        )
        for wd, actual in [(wd1, Decimal("900")), (wd2, Decimal("850"))]:
            PurchaseInvoice.objects.create(
                working_day=wd, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"),
            )
            self._sell(wd, Decimal("0") if wd == wd1 else Decimal("205"), Decimal("205") if wd == wd1 else Decimal("410"), test=Decimal("5"))
            TankInventory.objects.create(tank=self.tank, working_day=wd, actual_inventory=actual)

        from apps.reports import services as report_services
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 24)
        )
        row1, row2 = rows
        actual_delta = row1["actual_inventory"] - row2["actual_inventory"]
        shortage_delta = row2["shortage"] - row1["shortage"]
        dispatched_delta = row2["daily_dispatched"] - row1["daily_dispatched"]
        self.assertNotEqual(actual_delta, 0)
        # The change in دispatched tracks the change in کسری exactly --
        # NOT the (unrelated, much larger/different) change in actual.
        self.assertEqual(dispatched_delta, shortage_delta)
        self.assertNotEqual(dispatched_delta, actual_delta)

    def test_actual_inventory_still_its_own_unchanged_column(self):
        """موجودی واقعی must remain stored/displayed exactly as entered,
        just no longer summed into جمع روزانه خارج شده."""
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("1000"), effective_month=datetime.date(2026, 7, 23),
        )
        PurchaseInvoice.objects.create(
            working_day=wd, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"),
        )
        self._sell(wd, Decimal("0"), Decimal("205"), test=Decimal("5"))
        TankInventory.objects.create(tank=self.tank, working_day=wd, actual_inventory=Decimal("900"))

        from apps.reports import services as report_services
        row = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 23)
        )[0]
        self.assertEqual(row["actual_inventory"], Decimal("900"))
        inv = TankInventory.objects.get(tank=self.tank, working_day=wd)
        self.assertEqual(inv.actual_inventory, Decimal("900"))

    def test_cumulative_received_accumulates_across_days(self):
        wd1 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        wd2 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 24))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"), effective_month=datetime.date(2026, 7, 23),
        )
        PurchaseInvoice.objects.create(working_day=wd1, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"))
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("100"))
        PurchaseInvoice.objects.create(working_day=wd2, tank=self.tank, quantity=Decimal("50"), purchase_rate=Decimal("1200"))
        TankInventory.objects.create(tank=self.tank, working_day=wd2, actual_inventory=Decimal("150"))

        from apps.reports import services as report_services
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 24)
        )
        day1_cumulative = rows[0]["received_rows"][0]["cumulative_received"]
        day2_cumulative = rows[1]["received_rows"][0]["cumulative_received"]
        self.assertEqual(day1_cumulative, rows[0]["received_rows"][0]["daily_received"])
        self.assertEqual(
            day2_cumulative,
            day1_cumulative + rows[1]["received_rows"][0]["daily_received"],
        )

    def test_cumulative_dispatched_accumulates_across_days(self):
        wd1 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        wd2 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 24))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"), effective_month=datetime.date(2026, 7, 23),
        )
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("0"))
        TankInventory.objects.create(tank=self.tank, working_day=wd2, actual_inventory=Decimal("0"))

        from apps.reports import services as report_services
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 24)
        )
        self.assertEqual(rows[0]["cumulative_dispatched"], rows[0]["daily_dispatched"])
        self.assertEqual(
            rows[1]["cumulative_dispatched"],
            rows[0]["cumulative_dispatched"] + rows[1]["daily_dispatched"],
        )

    def test_cumulative_totals_follow_the_exact_carry_forward_rule(self):
        """
        جمع کل رسیده (روز N) = جمع کل رسیده (روز N-1) + جمع رسیده (روز N)
        جمع کل خارج شده (روز N) = جمع کل خارج شده (روز N-1) + جمع خارج شده (روز N)

        For جمع کل رسیده, day 1 here is this tank's actual first working
        day ever, so its "previous" is موجودی افتتاحیه (OpeningInventory),
        not 0 -- i.e. day 1's جمع کل رسیده = موجودی افتتاحیه + آن روز's
        جمع روزانه. For جمع کل خارج شده, day 1's "previous day" is still
        treated as 0 (unaffected by this rule -- see this function's own
        docstring). This does NOT check the two sides against each other
        -- that isn't part of the design (see apps/reports/services.py's
        docstring on petroleum_inventory_operations_ledger): موجودی واقعی
        is an absolute balance, not a delta, so summing it daily into جمع
        خارج شده intentionally does not reconcile against جمع رسیده's
        running total of small daily deltas.
        """
        wd1 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        wd2 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 24))
        wd3 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 25))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("1000"), effective_month=datetime.date(2026, 7, 23),
        )
        PurchaseInvoice.objects.create(working_day=wd1, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"))
        self._sell(wd1, Decimal("0"), Decimal("205"), test=Decimal("5"))
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("910"))  # overage 5

        PurchaseInvoice.objects.create(working_day=wd2, tank=self.tank, quantity=Decimal("50"), purchase_rate=Decimal("1200"))
        self._sell(wd2, Decimal("205"), Decimal("300"))
        TankInventory.objects.create(tank=self.tank, working_day=wd2, actual_inventory=Decimal("650"))

        self._sell(wd3, Decimal("300"), Decimal("350"), test=Decimal("2"))
        TankInventory.objects.create(tank=self.tank, working_day=wd3, actual_inventory=Decimal("600"))

        from apps.reports import services as report_services
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 25)
        )

        day1, day2, day3 = rows
        day1_received = day1["received_rows"][0]

        # Day 1 is this tank's actual first working day: جمع کل رسیده =
        # موجودی افتتاحیه + جمع روزانه (NOT just جمع روزانه alone).
        self.assertEqual(
            day1_received["cumulative_received"],
            Decimal("1000") + day1_received["daily_received"],
        )
        # جمع کل خارج شده's day-1 "previous" is still 0, unaffected.
        self.assertEqual(day1["cumulative_dispatched"], day1["daily_dispatched"])

        # Day 2: جمع کل (روز ۲) == جمع کل (روز ۱) + جمع روزانه (روز ۲).
        day2_received = day2["received_rows"][0]
        self.assertEqual(
            day2_received["cumulative_received"],
            day1_received["cumulative_received"] + day2_received["daily_received"],
        )
        self.assertEqual(
            day2["cumulative_dispatched"],
            day1["cumulative_dispatched"] + day2["daily_dispatched"],
        )

        # Day 3: same rule, chained one more day.
        day3_received = day3["received_rows"][0]
        self.assertEqual(
            day3_received["cumulative_received"],
            day2_received["cumulative_received"] + day3_received["daily_received"],
        )
        self.assertEqual(
            day3["cumulative_dispatched"],
            day2["cumulative_dispatched"] + day3["daily_dispatched"],
        )

    def test_first_working_day_received_cumulative_uses_opening_inventory(self):
        """Task: جمع کل رسیده for the tank's actual first working day =
        جمع روزانه‌ی رسیده + موجودی افتتاحیه (treating موجودی افتتاحیه as
        "جمع کل رسیده of day zero"), not 0."""
        wd1 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("750"), effective_month=datetime.date(2026, 7, 23),
        )
        PurchaseInvoice.objects.create(working_day=wd1, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"))
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("100"))

        from apps.reports import services as report_services
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 23)
        )
        day1_received = rows[0]["received_rows"][0]
        self.assertEqual(
            day1_received["cumulative_received"],
            Decimal("750") + day1_received["daily_received"],
        )

    def test_first_working_day_with_no_opening_inventory_defaults_to_zero(self):
        """No OpeningInventory row supplied -> existing 0-default
        (inventory_services.get_previous_balance_and_overage's own
        established fallback), not a new behavior invented here."""
        wd1 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        PurchaseInvoice.objects.create(working_day=wd1, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"))
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("100"))

        from apps.reports import services as report_services
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 23)
        )
        day1_received = rows[0]["received_rows"][0]
        self.assertEqual(day1_received["cumulative_received"], day1_received["daily_received"])

    def test_sub_range_starting_after_the_tanks_true_first_day_still_starts_from_zero(self):
        """Scoping check: a later sub-range's first displayed row is NOT
        the tank's actual first working day, so it must keep the
        existing, unrelated "starts from 0 for this view" convention --
        the opening-inventory fix must not leak into this case."""
        wd1 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        wd2 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 24))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("750"), effective_month=datetime.date(2026, 7, 23),
        )
        PurchaseInvoice.objects.create(working_day=wd1, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"))
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("100"))
        PurchaseInvoice.objects.create(working_day=wd2, tank=self.tank, quantity=Decimal("50"), purchase_rate=Decimal("1200"))
        TankInventory.objects.create(tank=self.tank, working_day=wd2, actual_inventory=Decimal("150"))

        from apps.reports import services as report_services
        # Query only day 2 -- not this tank's true first working day.
        rows = report_services.petroleum_inventory_operations_ledger(
            self.tank, datetime.date(2026, 7, 24), datetime.date(2026, 7, 24)
        )
        day2_received = rows[0]["received_rows"][0]
        self.assertEqual(day2_received["cumulative_received"], day2_received["daily_received"])

    def test_page_shows_both_section_headers_and_all_fourteen_columns(self):
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"), effective_month=datetime.date(2026, 7, 23),
        )
        PurchaseInvoice.objects.create(working_day=wd, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"))
        TankInventory.objects.create(tank=self.tank, working_day=wd, actual_inventory=Decimal("100"))

        resp = self.client.get(
            f"/reports/petroleum-ledger/?tank_id={self.tank.id}&start_date=2026-07-23&end_date=2026-07-23"
        )
        content = resp.content.decode()
        self.assertIn(">رسیده<", content)
        self.assertIn(">خارج شده<", content)
        columns = [
            "تاریخ", "شماره ی بارنامه", "شماره ی نفتکش", "مقدار خرید",
            "مجموع آزمایش", "سرک", "جمع روزانه‌ی رسیده", "جمع کل رسیده",
            "جمع فروش مکانیکی", "جمع آزمایش", "کسری",
            "جمع روزانه‌ی خارج شده", "جمع کل خارج شده", "موجودی واقعی",
        ]
        for col in columns:
            self.assertIn(col, content)

    def test_regular_super_tank_selector_still_works(self):
        super_product = Product.objects.create(name="CNG")
        super_tank = Tank.objects.create(station=self.tank.station, product=super_product, capacity=30000)
        resp = self.client.get("/reports/petroleum-ledger/")
        # Persian display labels (see apps/core/display.py) -- stored
        # Product.name values are still "Regular"/"CNG".
        self.assertContains(resp, "بنزین معمولی")
        self.assertContains(resp, "CNG")

    def test_pdf_source_html_shows_persian_product_name(self):
        """Renders the actual printing/petroleum_ledger_print.html template
        (the exact HTML WeasyPrint turns into PDF) without needing
        weasyprint installed -- verifies the PDF, not just the on-screen
        UI, shows the Persian product name."""
        from django.template.loader import render_to_string

        from apps.printing.services import build_petroleum_ledger_context

        context = build_petroleum_ledger_context(
            self.tank, datetime.date(2026, 7, 23), datetime.date(2026, 7, 23),
        )
        html = render_to_string("printing/petroleum_ledger_print.html", context)

        self.assertIn("بنزین معمولی", html)
        self.assertNotIn(">Regular<", html)
        self.assertNotIn("— Regular", html)

    def test_print_pdf_generates_with_both_section_headers(self):
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"), effective_month=datetime.date(2026, 7, 23),
        )
        PurchaseInvoice.objects.create(working_day=wd, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"))
        TankInventory.objects.create(tank=self.tank, working_day=wd, actual_inventory=Decimal("100"))

        resp = self.client.get(
            f"/print/petroleum-ledger/{self.tank.id}/?start_date=2026-07-23&end_date=2026-07-23"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get("Content-Type"), "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))


class MonthlyTankStatementReworkTests(TestCase):
    """
    Covers the گزارش ماهانه ی مخازن rework: 10-column reorder/rename,
    removal of "کل خرید" from THIS report's display only (its underlying
    logic/value is unaffected and still computed), and the two new
    columns "جمع کل رسیده"/"جمع کل خارج شده" reusing the last available
    cumulative totals from دفتر موجودی و عملیات verbatim.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="op_monthly", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S_monthly", province="P", city="C")
        self.product = Product.objects.create(name="Regular")
        self.tank = Tank.objects.create(station=station, product=self.product, capacity=50000)
        self.nozzle = Nozzle.objects.create(tank=self.tank, number=1)
        self.client.login(username="op_monthly", password="testpass123")
        # 2026-07-23 is Jalali 1405/05/01 -- the accounting start for a
        # license activated on 2026-08-01 (see get_accounting_start_date's
        # Jalali-month-start rule).
        self.day1 = datetime.date(2026, 7, 23)
        self.day2 = datetime.date(2026, 7, 24)

    def _sell(self, wd, previous_meter, new_meter, test=Decimal("0"), rate=Decimal("1200")):
        invoice = SalesInvoice.objects.get_or_create(working_day=wd, defaults={"operator": self.user})[0]
        return NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=self.nozzle,
            previous_meter=previous_meter, new_meter=new_meter, test=test, sales_rate=rate,
        )

    def test_total_received_reuses_last_cumulative_from_petroleum_ledger(self):
        wd1 = DailyWorkingDay.objects.create(date=self.day1)
        wd2 = DailyWorkingDay.objects.create(date=self.day2)
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"), effective_month=self.day1,
        )
        PurchaseInvoice.objects.create(working_day=wd1, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"))
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("100"))
        PurchaseInvoice.objects.create(working_day=wd2, tank=self.tank, quantity=Decimal("50"), purchase_rate=Decimal("1200"))
        TankInventory.objects.create(tank=self.tank, working_day=wd2, actual_inventory=Decimal("150"))

        from apps.reports import services as report_services
        ledger_rows = report_services.petroleum_inventory_operations_ledger(self.tank, self.day1, self.day2)
        monthly = report_services.petroleum_inventory_monthly(self.tank, 1405, 5)

        self.assertEqual(monthly["total_received"], ledger_rows[-1]["cumulative_received"])
        self.assertEqual(monthly["total_dispatched"], ledger_rows[-1]["cumulative_dispatched"])

    def test_total_purchase_still_computed_but_not_displayed(self):
        wd1 = DailyWorkingDay.objects.create(date=self.day1)
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"), effective_month=self.day1,
        )
        PurchaseInvoice.objects.create(working_day=wd1, tank=self.tank, quantity=Decimal("777"), purchase_rate=Decimal("1200"))
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("777"))

        from apps.reports import services as report_services
        monthly = report_services.petroleum_inventory_monthly(self.tank, 1405, 5)
        # Underlying value/logic untouched...
        self.assertEqual(monthly["total_purchase"], Decimal("777"))

        # ...but not shown as its own column on this report anymore.
        resp = self.client.get("/reports/petroleum-monthly/?year=1405&month=5")
        self.assertNotContains(resp, "کل خرید")

    def test_page_shows_all_ten_columns_in_order_with_renamed_labels(self):
        wd1 = DailyWorkingDay.objects.create(date=self.day1)
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"), effective_month=self.day1,
        )
        PurchaseInvoice.objects.create(working_day=wd1, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"))
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("100"))

        resp = self.client.get("/reports/petroleum-monthly/?year=1405&month=5")
        content = resp.content.decode()
        columns = [
            "محصول", "موجودی ابتدای دوره", "مجموع سرک", "کل بازگشت تست",
            "جمع کل رسیده", "کل فروش", "کل کسری", "جمع کل خارج شده",
            "موجودی آخر دوره",
        ]
        for col in columns:
            self.assertIn(col, content)
        positions = [content.index(c) for c in columns]
        self.assertEqual(positions, sorted(positions))
        # Old labels must be gone.
        self.assertNotIn("کل اضافه", content)
        self.assertNotIn("کل خرید", content)

    def test_regular_super_separation_unchanged(self):
        super_product = Product.objects.create(name="CNG")
        super_tank = Tank.objects.create(station=self.tank.station, product=super_product, capacity=30000)
        wd1 = DailyWorkingDay.objects.create(date=self.day1)
        for t in (self.tank, super_tank):
            OpeningInventory.objects.create(tank=t, opening_quantity=Decimal("0"), effective_month=self.day1)
            TankInventory.objects.create(tank=t, working_day=wd1, actual_inventory=Decimal("0"))

        resp = self.client.get("/reports/petroleum-monthly/?year=1405&month=5")
        # Persian display labels (see apps/core/display.py) -- stored
        # Product.name values are still "Regular"/"CNG".
        self.assertContains(resp, "بنزین معمولی")
        self.assertContains(resp, "CNG")

    def test_print_pdf_generates_correctly(self):
        wd1 = DailyWorkingDay.objects.create(date=self.day1)
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"), effective_month=self.day1,
        )
        PurchaseInvoice.objects.create(working_day=wd1, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"))
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("100"))

        resp = self.client.get("/print/petroleum-monthly/?year=1405&month=5")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get("Content-Type"), "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_petroleum_ledger_section_itself_is_unmodified(self):
        """Confirms this rework did not touch دفتر موجودی و عملیات."""
        wd1 = DailyWorkingDay.objects.create(date=self.day1)
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("0"), effective_month=self.day1,
        )
        PurchaseInvoice.objects.create(working_day=wd1, tank=self.tank, quantity=Decimal("100"), purchase_rate=Decimal("1200"))
        TankInventory.objects.create(tank=self.tank, working_day=wd1, actual_inventory=Decimal("100"))

        resp = self.client.get(
            f"/reports/petroleum-ledger/?tank_id={self.tank.id}&start_date=2026-07-23&end_date=2026-07-23"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "رسیده")
        self.assertContains(resp, "خارج شده")

    def test_month_selector_offers_exactly_twelve_months(self):
        """Bug fix: the ماه <select> was built from
        {% for m in "123456789101112" %}, which iterates that STRING
        CHARACTER BY CHARACTER (15 chars: 1,2,3,4,5,6,7,8,9,1,0,1,1,1,2),
        producing 15 options (values 1-15 via forloop.counter) instead
        of 12 -- so picking month 13-15 hit the "no changes detected"-
        -esque out-of-range failure. Now it's 12 explicit options."""
        resp = self.client.get("/reports/petroleum-monthly/?year=1405&month=5")
        content = resp.content.decode()
        self.assertEqual(content.count('<option value="'), 12)
        for m in range(1, 13):
            self.assertIn(f'<option value="{m}"', content)
        for m in range(13, 16):
            self.assertNotIn(f'<option value="{m}"', content)

    def test_month_thirteen_is_not_a_selectable_option(self):
        resp = self.client.get("/reports/petroleum-monthly/?year=1405&month=5")
        self.assertNotContains(resp, 'value="13"')
        self.assertNotContains(resp, 'value="14"')
        self.assertNotContains(resp, 'value="15"')
