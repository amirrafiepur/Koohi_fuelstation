"""
A day's سرک (overage) must not affect the کسری (shortage) of the following
days -- and therefore not their «جمع روزانه خارج شده» / «جمع کل خارج شده».

Scenario (Regular tank, opening inventory 1,000, no purchases, no tests):

    day   sales   actual    meaning
    1       0     1,014     14 more than the book figure -> سرک 14
    2     100       914     exactly 1,014 - 100: nothing lost -> NO کسری
    3      50       864     exactly 914 - 50: nothing lost    -> NO کسری

Before the fix, day 1's سرک of 14 was added to day 2's total inventory, so day 2
showed a false کسری of 14 (dispatched 114 instead of 100) and every cumulative
«جمع کل خارج شده» after it was 14 too high.
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.inventory import services
from apps.inventory.models import OpeningInventory, TankInventory
from apps.license.models import License
from apps.reports import services as report_services
from apps.sales.models import NozzleSale, SalesInvoice
from apps.stations.models import Nozzle, Product, Station, Tank
from apps.workday.models import DailyWorkingDay

D = Decimal
User = get_user_model()
DAYS = [datetime.date(2026, 7, 23), datetime.date(2026, 7, 24), datetime.date(2026, 7, 25)]


class OverageIsNotCarriedForwardTests(TestCase):
    def setUp(self):
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        self.user = User.objects.create_user(username="op1", password="testpass123")
        station = Station.objects.create(name="S", province="P", city="C")
        self.tank = Tank.objects.create(station=station, product=Product.objects.create(name="Regular"), capacity=50000)
        nozzle = Nozzle.objects.create(tank=self.tank, number=1)
        OpeningInventory.objects.create(tank=self.tank, opening_quantity=D(1000), effective_month=DAYS[0])
        meter = D(0)
        self.days = []
        for date, sales, actual in zip(DAYS, (0, 100, 50), (1014, 914, 864)):
            wd = DailyWorkingDay.objects.create(date=date)
            invoice = SalesInvoice.objects.create(working_day=wd, operator=self.user)
            NozzleSale.objects.create(sales_invoice=invoice, nozzle=nozzle, previous_meter=meter,
                                      new_meter=meter + sales, test=D(0), sales_rate=D(1000))
            meter += sales
            TankInventory.objects.create(working_day=wd, tank=self.tank, actual_inventory=D(actual))
            self.days.append(wd)

    def test_inventory_figures_per_day(self):
        # (total, theoretical, shortage, overage)
        self.assertEqual(services.compute_tank_inventory(self.tank, self.days[0]), (D(1000), D(1000), D(0), D(14)))
        self.assertEqual(services.compute_tank_inventory(self.tank, self.days[1]), (D(1014), D(914), D(0), D(0)))
        self.assertEqual(services.compute_tank_inventory(self.tank, self.days[2]), (D(914), D(864), D(0), D(0)))

    def test_ledger_shortage_and_dispatched_totals_are_not_inflated(self):
        rows = report_services.petroleum_inventory_operations_ledger(self.tank, DAYS[0], DAYS[2])
        self.assertEqual([r["overage"] for r in rows], [D(14), D(0), D(0)])
        self.assertEqual([r["shortage"] for r in rows], [D(0), D(0), D(0)])                 # was 0, 14, 0
        self.assertEqual([r["daily_dispatched"] for r in rows], [D(0), D(100), D(50)])      # was 0, 114, 50
        self.assertEqual([r["cumulative_dispatched"] for r in rows], [D(0), D(100), D(150)])  # was 0, 114, 164
        totals = report_services.petroleum_inventory_ledger_totals(rows)
        self.assertEqual((totals["total_overage"], totals["total_shortage"]), (D(14), D(0)))

    def test_actual_inventory_entry_page_does_not_add_yesterdays_overage(self):
        self.client.login(username="op1", password="testpass123")
        resp = self.client.get(f"/inventory/{DAYS[1]}/tank/{self.tank.id}/actual/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["previous_balance"], D(1014))
        self.assertEqual(resp.context["total_inventory"], D(1014))          # was 1,028
        self.assertEqual(resp.context["theoretical_inventory"], D(914))     # was 928

    def test_a_real_shortage_still_shows(self):
        TankInventory.objects.filter(working_day=self.days[1]).update(actual_inventory=D(900))   # 14 really missing
        total, theoretical, shortage, overage = services.compute_tank_inventory(self.tank, self.days[1])
        self.assertEqual((total, theoretical, shortage, overage), (D(1014), D(914), D(14), D(0)))
        rows = report_services.petroleum_inventory_operations_ledger(self.tank, DAYS[0], DAYS[2])
        self.assertEqual(rows[1]["daily_dispatched"], D(114))                # 100 sold + 14 shortage, counted once
        # Day 3 starts from day 2's measured 900, so it adds nothing on top of day 2's shortage either.
        self.assertEqual(services.compute_tank_inventory(self.tank, self.days[2])[0], D(900))
