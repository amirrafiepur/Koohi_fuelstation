"""
آزمایش (test liters) in the shortage / overage calculation.

The test liters leave the nozzle through the meter and go BACK into the tank, so

    operation (meter)        = mechanical sales + test
    total inventory (جمع کل)  = previous actual + purchases + test + previous overage
    theoretical inventory    = total - (mechanical sales + test)          [= total - operation]
    shortage / overage       = theoretical vs. actual

The test therefore cancels out: the tank physically loses only the mechanical sales, and a
perfect day with a test of T liters shows no shortage (before this rule it showed a shortage of T).

All figures below are worked by hand. Regular tank, opening inventory 100,000 unless stated.
"""

import datetime
import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.core.test_number_display import numeric_cells, pdf_text, render_pdf_with_html
from apps.inventory import services as inv
from apps.inventory.models import OpeningInventory, TankInventory
from apps.license.models import License
from apps.purchases.models import PurchaseInvoice
from apps.reports import services as report_services
from apps.sales.models import NozzleSale, SalesInvoice
from apps.statement.services import build_statement_rows
from apps.stations.models import Nozzle, Tank
from apps.workday.models import DailyWorkingDay

User = get_user_model()
D = Decimal
d = datetime.date

DAY1, DAY2, DAY3 = d(2026, 7, 24), d(2026, 7, 25), d(2026, 7, 26)


def clear_days():
    for model in (TankInventory, PurchaseInvoice, NozzleSale, SalesInvoice, DailyWorkingDay):
        model.objects.all().delete()


class TestLitersBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=d(2026, 8, 1), duration_days=365)     # accounting starts 2026-07-23
        call_command("seed_station", stdout=io.StringIO())
        self.tank = Tank.objects.get(product__name="Regular")
        self.nozzle = Nozzle.objects.get(tank__product__name="Regular", number=1)
        OpeningInventory.objects.update_or_create(
            tank=self.tank, effective_month=d(2026, 7, 23), defaults={"opening_quantity": D(100000)})
        self.client.login(username="op1", password="testpass123")

    def day(self, date, operation, test, actual, purchases=()):
        """One working day: meter operation, test liters, purchases, and the entered actual inventory."""
        wd, _ = DailyWorkingDay.objects.get_or_create(date=date)
        invoice, _ = SalesInvoice.objects.get_or_create(working_day=wd, defaults={"operator": self.user})
        last = NozzleSale.objects.filter(nozzle=self.nozzle).order_by("-id").first()
        previous = last.new_meter if last else D(0)
        NozzleSale.objects.create(sales_invoice=invoice, nozzle=self.nozzle, previous_meter=previous,
                                  new_meter=previous + D(operation), test=D(test), sales_rate=D(1200))
        for quantity in purchases:
            PurchaseInvoice.objects.create(working_day=wd, tank=self.tank, quantity=quantity, purchase_rate=D(1200),
                                           program_number="1", tanker_number="T")
        if actual is not None:
            TankInventory.objects.create(tank=self.tank, working_day=wd, actual_inventory=D(actual))
        return wd

    def compute(self, wd):
        return inv.compute_tank_inventory(self.tank, wd)


class SingleDayExamples(TestLitersBase):
    """The reported case: a day with a test of 100."""

    def test_control_day_without_a_test(self):
        wd = self.day(DAY1, operation=900, test=0, actual=99100)             # tank lost 900
        self.assertEqual(self.compute(wd), (D(100000), D(99100), D(0), D(0)))

    def test_perfect_day_with_a_test_of_100_has_no_shortage(self):
        """Meter 1000 = 900 sold + 100 test (returned). The tank lost 900 -> nothing is missing."""
        wd = self.day(DAY1, operation=1000, test=100, actual=99100)
        total, theoretical, shortage, overage = self.compute(wd)
        self.assertEqual(total, D(100100))                                    # 100,000 + test 100
        self.assertEqual(theoretical, D(99100))                              # 100,100 - (900 + 100)
        self.assertEqual((shortage, overage), (D(0), D(0)))                  # was shortage 100 before the fix

    def test_real_shortage_is_measured_exactly_on_a_test_day(self):
        wd = self.day(DAY1, operation=1000, test=100, actual=99060)          # 40 liters really missing
        _, theoretical, shortage, overage = self.compute(wd)
        self.assertEqual((theoretical, shortage, overage), (D(99100), D(40), D(0)))      # was 140

    def test_real_overage_is_measured_exactly_on_a_test_day(self):
        wd = self.day(DAY1, operation=1000, test=100, actual=99140)          # 40 liters extra
        _, theoretical, shortage, overage = self.compute(wd)
        self.assertEqual((theoretical, shortage, overage), (D(99100), D(0), D(40)))      # was shortage 60

    def test_same_sales_with_any_amount_of_test_gives_the_same_verdict(self):
        """900 liters sold; the meter reading differs only by how much test was run."""
        for test in (0, 5, 100, 250, 600):
            clear_days()
            wd = self.day(DAY1, operation=900 + test, test=test, actual=99100)
            _, theoretical, shortage, overage = self.compute(wd)
            self.assertEqual((theoretical, shortage, overage), (D(99100), D(0), D(0)), f"test={test}")

    def test_theoretical_is_total_minus_the_whole_meter_operation(self):
        for operation, test in ((1000, 100), (900, 0), (1500, 600), (320, 20)):
            clear_days()
            wd = self.day(DAY1, operation=operation, test=test, actual=99000)
            total, theoretical, _, _ = self.compute(wd)
            self.assertEqual(theoretical, total - D(operation), (operation, test))

    def test_the_shared_formula_function(self):
        self.assertEqual(inv.compute_theoretical_inventory(D(1105), D(200), D(5)), D(900))
        self.assertEqual(inv.compute_theoretical_inventory(D(100100), D(900), D(100)), D(99100))
        self.assertEqual(inv.compute_theoretical_inventory(D(500), D(100), D(0)), D(400))     # no test: unchanged


class MultiDayAndLedgerExamples(TestLitersBase):
    """
    Three days (opening 100,000), all with a test:
      d1  purchase 10,000  meter 1,000  test 100  (sold 900)  perfect      actual 109,100
      d2  none             meter   500  test  50  (sold 450)  perfect      actual 108,650
      d3  purchase  5,000  meter   820  test  20  (sold 800)  30 missing   actual 112,820
    Per day  (received = purchases + test + سرک ; dispatched = sales + test + کسری):
      d1  received 10,100   dispatched 900+100+0  = 1,000   cumulative: received 110,100  dispatched 1,000
      d2  received     50   dispatched 450+ 50+0  =   500                         110,150              1,500
      d3  received  5,020   dispatched 800+ 20+30 =   850                         115,170              2,350
    mechanical sales 900 / 450 / 800 = 2,150 ; tests 170 ; shortage 30 ; overage 0 ; purchases 15,000
    """

    def setUp(self):
        super().setUp()
        self.d1 = self.day(DAY1, 1000, 100, "109100", purchases=[10000])
        self.d2 = self.day(DAY2, 500, 50, "108650")
        self.d3 = self.day(DAY3, 820, 20, "112820", purchases=[5000])

    def ledger_rows(self):
        return report_services.petroleum_inventory_operations_ledger(self.tank, DAY1, DAY3)

    def test_each_day_is_calculated_correctly(self):
        results = [self.compute(wd) for wd in (self.d1, self.d2, self.d3)]
        self.assertEqual(results, [
            (D(110100), D(109100), D(0), D(0)),
            (D(109150), D(108650), D(0), D(0)),
            (D(113670), D(112850), D(30), D(0)),
        ])

    def test_ledger_daily_and_cumulative_dispatched_totals(self):
        rows = self.ledger_rows()
        self.assertEqual([r["shortage"] for r in rows], [D(0), D(0), D(30)])
        self.assertEqual([r["daily_sales"] for r in rows], [D(900), D(450), D(800)])          # فروش (unchanged)
        self.assertEqual([r["daily_dispatched"] for r in rows], [D(1000), D(500), D(850)])    # جمع روزانه خارج شده
        self.assertEqual([r["cumulative_dispatched"] for r in rows], [D(1000), D(1500), D(2350)])   # جمع کل خارج شده

    def test_ledger_received_side_is_consistent(self):
        rows = self.ledger_rows()
        self.assertEqual([r["daily_received"] for r in rows], [D(10100), D(50), D(5020)])
        self.assertEqual([r["cumulative_received"] for r in rows], [D(110100), D(110150), D(115170)])

    def test_dispatched_is_the_meter_operation_plus_any_real_shortage(self):
        for row, operation in zip(self.ledger_rows(), (D(1000), D(500), D(820))):
            self.assertEqual(row["daily_dispatched"], operation + row["shortage"])

    def test_ledger_totals_strip(self):
        totals = report_services.petroleum_inventory_ledger_totals(self.ledger_rows())
        self.assertEqual((totals["total_purchase"], totals["total_overage"], totals["total_test_received"],
                          totals["total_sales"], totals["total_shortage"], totals["total_test_dispatched"]),
                         (D(15000), D(0), D(170), D(2150), D(30), D(170)))          # shortage 30, not 200

    def test_ledger_screen_and_pdf_show_the_corrected_figures(self):
        screen = numeric_cells(self.client.get(
            f"/reports/petroleum-ledger/?tank_id={self.tank.id}&start_date=2026-07-24&end_date=2026-07-26").content.decode())
        resp, html = render_pdf_with_html(
            self.client, f"/print/petroleum-ledger/{self.tank.id}/?start_date=2026-07-24&end_date=2026-07-26")
        pdf = numeric_cells(html)
        for cells in (screen, pdf):
            for value in ("1,000", "1,500", "2,350", "850", "2,150", "110,100", "115,170"):
                self.assertIn(value, cells, value)
            self.assertNotIn("1,100", cells)                              # the old inflated dispatched figure for d1
            self.assertNotIn("2,520", cells)                               # old cumulative (2,350 + 170 inflated shortage)
        self.assertIn("2,350", pdf_text(resp.content))

    def test_overage_is_carried_into_the_next_day_instead_of_being_lost(self):
        """Test day with 40 extra liters, then a normal day. The 40 must carry into day 2's total."""
        clear_days()
        wd1 = self.day(DAY1, operation=1000, test=100, actual=99140)         # overage 40 (was shown as shortage 60)
        wd2 = self.day(DAY2, operation=500, test=0, actual=98680)            # 99,140 + 40 carried - 500
        self.assertEqual(self.compute(wd1)[2:], (D(0), D(40)))
        self.assertEqual(self.compute(wd2), (D(99180), D(98680), D(0), D(0)))

    def test_viewing_changes_no_stored_data(self):
        def snapshot():
            return (list(TankInventory.objects.values_list("actual_inventory", flat=True).order_by("id")),
                    list(NozzleSale.objects.values_list("test", "new_meter").order_by("id")))
        before = snapshot()
        self.ledger_rows()
        self.client.get(f"/reports/petroleum-ledger/?tank_id={self.tank.id}&start_date=2026-07-24&end_date=2026-07-26")
        self.assertEqual(before, snapshot())


class OtherScreensFollow(MultiDayAndLedgerExamples):
    """Same three days: the monthly tank report, the statement and the inventory screens agree."""

    def test_monthly_tank_report(self):
        row = report_services.petroleum_inventory_monthly(self.tank, 1405, 5)
        self.assertEqual((row["total_shortage"], row["total_overage"], row["total_sales"], row["total_test_return"]),
                         (D(30), D(0), D(2150), D(170)))
        self.assertEqual((row["total_received"], row["total_dispatched"]), (D(115170), D(2350)))

    def test_statement_shortage_commission_and_balance(self):
        regular = {r["product"].name: r for r in build_statement_rows(1405, 5)}["Regular"]
        self.assertEqual(regular["total_shortage"], D(30))                    # was 200 (100 + 50 + 20 + 30)
        self.assertEqual(regular["commission"], D("20.00"))                   # 30 x 10000 / 15,000 purchases
        self.assertEqual(regular["unauthorized_shortage_shown"], D("0.00"))   # below the threshold of 45
        # received = 100,000 + 15,000 + 170 + 0 ; dispatched = 2,150 + 170 + 30 + ending 112,820: the statement balances
        self.assertEqual(regular["received_total"], D(115170))
        self.assertEqual(regular["dispatched_total"], D(115170))

    def test_a_perfect_month_with_tests_balances_and_has_no_commission(self):
        TankInventory.objects.filter(working_day=self.d3).update(actual_inventory=D("112850"))     # no real shortage
        regular = {r["product"].name: r for r in build_statement_rows(1405, 5)}["Regular"]
        self.assertEqual((regular["total_shortage"], regular["commission"]), (D(0), D("0.00")))
        self.assertEqual(regular["received_total"], regular["dispatched_total"])

    def test_inventory_day_page_shows_the_corrected_theoretical_and_shortage(self):
        html = self.client.get(f"/inventory/{DAY3.isoformat()}/").content.decode()
        self.assertRegex(html, r"موجودی غیرواقعی</div>\s*<div[^>]*>\s*112,850\s*</div>")
        self.assertRegex(html, r"کسری</div>\s*<div[^>]*>\s*30\s*</div>")

    def test_the_entry_page_and_the_calculation_agree_before_and_after_saving(self):
        """Entry page (no actual yet) and the calculation (after saving) must show the same theoretical."""
        TankInventory.objects.filter(working_day=self.d3).delete()
        url = f"/inventory/{DAY3.isoformat()}/tank/{self.tank.id}/actual/"
        self.assertRegex(self.client.get(url).content.decode(), r"موجودی غیرواقعی</div>\s*<div[^>]*>\s*112,850\s*</div>")
        TankInventory.objects.create(tank=self.tank, working_day=self.d3, actual_inventory=D("112820"))
        self.assertEqual(self.compute(self.d3)[1], D(112850))
        self.assertRegex(self.client.get(url).content.decode(), r"موجودی غیرواقعی</div>\s*<div[^>]*>\s*112,850\s*</div>")
