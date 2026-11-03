"""
Tank inventory tests -- covering the corrected non-circular Overage
carry-forward rule and the opening-inventory chain, using the worked
example from the implementation spec (§60).
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.inventory import services
from apps.inventory.models import TankInventory, OpeningInventory
from apps.license.models import License
from apps.purchases.models import PurchaseInvoice
from apps.sales.models import SalesInvoice, NozzleSale
from apps.stations.models import Station, Product, Tank, Nozzle
from apps.workday.models import DailyWorkingDay

User = get_user_model()


class TankInventoryChainTests(TestCase):
    def setUp(self):
        # 2026-08-01 is Jalali 1405/05/10 -- the accounting start (day 1
        # of that Jalali month) is Gregorian 2026-07-23.
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        self.station = Station.objects.create(name="Test Station", province="P", city="C")
        self.product = Product.objects.create(name="Regular")
        self.tank = Tank.objects.create(station=self.station, product=self.product, capacity=50000)
        self.nozzle = Nozzle.objects.create(tank=self.tank, number=1)
        self.user = User.objects.create_user(username="op1", password="x")

        self.day1 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23))
        self.day2 = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 24))

    def _make_nozzle_sale(self, working_day, previous_meter, new_meter, test):
        invoice, _ = SalesInvoice.objects.get_or_create(
            working_day=working_day, defaults={"operator": self.user}
        )
        return NozzleSale.objects.create(
            sales_invoice=invoice,
            nozzle=self.nozzle,
            previous_meter=previous_meter,
            new_meter=new_meter,
            test=test,
            sales_rate=Decimal("1200"),
        )

    def test_day_one_uses_opening_inventory_and_matches_spec_example(self):
        # Spec §60 worked example, CORRECTED for the test liters.
        # Opening Inventory = 1000, Purchase = 100, Test = 5, Sales = 200 (operation 205).
        # The original example expected Theoretical = 905 (Total 1105 - Sales 200), which
        # added the test back into the total but never took it out again. The confirmed
        # rule is Theoretical = Total - (Sales + Test) = 1105 - 205 = 900: the tank really
        # loses only the 200 sold (the 5 of test goes back in), so a perfect day has
        # Actual = 1000 + 100 - 200 = 900 -> Total=1105, Theoretical=900, Shortage=0, Overage=0
        OpeningInventory.objects.create(
            tank=self.tank, opening_quantity=Decimal("1000"), effective_month=datetime.date(2026, 7, 23)
        )
        PurchaseInvoice.objects.create(
            working_day=self.day1, tank=self.tank, quantity=100, purchase_rate=Decimal("1200")
        )
        # Sales of 200 with test of 5: operation - test = mechanical sales.
        # previous=0, new=205, test=5 -> operation=205, mechanical_sales=200.
        self._make_nozzle_sale(self.day1, previous_meter=Decimal("0"), new_meter=Decimal("205"), test=Decimal("5"))

        TankInventory.objects.create(
            working_day=self.day1, tank=self.tank, actual_inventory=Decimal("900")
        )

        total, theoretical, shortage, overage = services.compute_tank_inventory(self.tank, self.day1)
        self.assertEqual(total, Decimal("1105"))
        self.assertEqual(theoretical, Decimal("900"))
        self.assertEqual(shortage, Decimal("0"))
        self.assertEqual(overage, Decimal("0"))

        # The old spec example's actual (905) is now 5 above the corrected theoretical: a real overage.
        TankInventory.objects.filter(working_day=self.day1, tank=self.tank).update(actual_inventory=Decimal("905"))
        _, theoretical, shortage, overage = services.compute_tank_inventory(self.tank, self.day1)
        self.assertEqual((theoretical, shortage, overage), (Decimal("900"), Decimal("0"), Decimal("5")))

    def test_day_two_uses_day_ones_actual_and_overage_not_its_own(self):
        # Day 1: no opening inventory row (defaults to 0), no purchase/sales,
        # Actual = 10 -> Theoretical = 0 -> Overage = 10.
        TankInventory.objects.create(
            working_day=self.day1, tank=self.tank, actual_inventory=Decimal("10")
        )
        total1, theoretical1, shortage1, overage1 = services.compute_tank_inventory(
            self.tank, self.day1
        )
        self.assertEqual(overage1, Decimal("10"))

        # Day 2: no purchase/sales either. Previous Balance = 10 (day1 actual),
        # Previous Overage = 10 (day1's own overage, carried forward).
        # Total = 10 + 0 + 0 + 10 = 20. If Actual = 20 -> Theoretical = 20 ->
        # shortage=overage=0, proving day 2 did NOT use its own (zero) overage
        # circularly but correctly carried day 1's.
        TankInventory.objects.create(
            working_day=self.day2, tank=self.tank, actual_inventory=Decimal("20")
        )
        total2, theoretical2, shortage2, overage2 = services.compute_tank_inventory(
            self.tank, self.day2
        )
        self.assertEqual(total2, Decimal("20"))
        self.assertEqual(theoretical2, Decimal("20"))
        self.assertEqual(shortage2, Decimal("0"))
        self.assertEqual(overage2, Decimal("0"))

    def test_missing_actual_inventory_raises(self):
        with self.assertRaises(ValueError):
            services.compute_tank_inventory(self.tank, self.day1)

    def test_shortage_and_overage_never_both_nonzero(self):
        TankInventory.objects.create(
            working_day=self.day1, tank=self.tank, actual_inventory=Decimal("0")
        )
        total, theoretical, shortage, overage = services.compute_tank_inventory(
            self.tank, self.day1
        )
        self.assertTrue(shortage == 0 or overage == 0)
        self.assertGreaterEqual(shortage, 0)
        self.assertGreaterEqual(overage, 0)


# ---------------------------------------------------------------------------
# HTTP-level integration tests for the Phase 6 tank inventory workflow.
# ---------------------------------------------------------------------------

from django.test import TestCase as _TestCase

User_ = get_user_model()


class InventoryWorkflowHttpTests(_TestCase):
    def setUp(self):
        self.user = User_.objects.create_user(username="op1", password="testpass123")
        # 2026-08-01 is Jalali 1405/05/10 -- accounting start (day 1 of
        # that Jalali month) is Gregorian 2026-07-23, so that's the date
        # that must trigger the "day 1" opening-inventory prompt below.
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S", province="P", city="C")
        self.product = Product.objects.create(name="Regular")
        self.tank = Tank.objects.create(station=station, product=self.product, capacity=50000)
        self.client.login(username="op1", password="testpass123")
        self.day1 = "2026-07-23"
        self.day2 = "2026-07-24"

    def test_day_detail_prompts_for_opening_inventory_on_first_day(self):
        resp = self.client.get(f"/inventory/{self.day1}/")
        self.assertContains(resp, "موجودی افتتاحیه")

    def test_opening_inventory_defaults_to_zero_and_is_not_forced(self):
        resp = self.client.get(f"/inventory/{self.day1}/tank/{self.tank.id}/opening/")
        self.assertContains(resp, 'value="0"')

    def test_can_submit_opening_inventory_of_zero(self):
        resp = self.client.post(
            f"/inventory/{self.day1}/tank/{self.tank.id}/opening/",
            {"opening_quantity": "0"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            OpeningInventory.objects.filter(tank=self.tank, opening_quantity=Decimal("0")).exists()
        )

    def test_can_submit_a_real_opening_inventory_value(self):
        self.client.post(
            f"/inventory/{self.day1}/tank/{self.tank.id}/opening/",
            {"opening_quantity": "1000"},
        )
        opening = OpeningInventory.objects.get(tank=self.tank)
        self.assertEqual(opening.opening_quantity, Decimal("1000"))

    def test_actual_inventory_prompt_shown_when_missing(self):
        self.client.post(
            f"/inventory/{self.day1}/tank/{self.tank.id}/opening/",
            {"opening_quantity": "1000"},
        )
        resp = self.client.get(f"/inventory/{self.day1}/")
        self.assertContains(resp, "موجودی واقعی برای این مخزن")

    def test_full_first_day_flow_matches_spec_example(self):
        # Reproduces the architecture doc's worked example (§60):
        # Opening=1000, Purchase=100, Test=5(via sales), Sales=200,
        # Actual=905 -> Total=1105, Theoretical=905, Shortage=0, Overage=0.
        self.client.post(
            f"/inventory/{self.day1}/tank/{self.tank.id}/opening/",
            {"opening_quantity": "1000"},
        )
        PurchaseInvoice.objects.create(
            working_day=DailyWorkingDay.objects.get(date=self.day1),
            tank=self.tank, quantity=100, purchase_rate=Decimal("1200"),
        )
        nozzle = Nozzle.objects.create(tank=self.tank, number=1)
        invoice = SalesInvoice.objects.create(
            working_day=DailyWorkingDay.objects.get(date=self.day1), operator=self.user
        )
        NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=nozzle,
            previous_meter=Decimal("0"), new_meter=Decimal("205"), test=Decimal("5"),
            sales_rate=Decimal("1200"),
        )
        self.client.post(
            f"/inventory/{self.day1}/tank/{self.tank.id}/actual/",
            {"actual_inventory": "905"},
        )
        resp = self.client.get(f"/inventory/{self.day1}/")
        self.assertContains(resp, "1,105")  # total inventory
        self.assertContains(resp, "905")   # theoretical inventory + actual

    def test_day_two_does_not_prompt_for_opening_inventory(self):
        # Day 2 is not day 1 of the accounting month -- no opening prompt.
        self.client.post(
            f"/inventory/{self.day1}/tank/{self.tank.id}/opening/",
            {"opening_quantity": "0"},
        )
        self.client.post(
            f"/inventory/{self.day1}/tank/{self.tank.id}/actual/",
            {"actual_inventory": "0"},
        )
        resp = self.client.get(f"/inventory/{self.day2}/")
        self.assertNotContains(resp, "موجودی افتتاحیه مخزن")

    def test_day_two_uses_day_ones_actual_and_carried_overage_not_own(self):
        # Mirrors the service-level circularity regression test, but
        # exercised through the actual HTTP views end to end.
        self.client.post(
            f"/inventory/{self.day1}/tank/{self.tank.id}/opening/",
            {"opening_quantity": "0"},
        )
        self.client.post(
            f"/inventory/{self.day1}/tank/{self.tank.id}/actual/",
            {"actual_inventory": "10"},  # theoretical=0 -> overage=10
        )
        self.client.post(
            f"/inventory/{self.day2}/tank/{self.tank.id}/actual/",
            {"actual_inventory": "20"},  # prev balance=10 + prev overage=10 = 20
        )
        total, theoretical, shortage, overage = services.compute_tank_inventory(
            self.tank, DailyWorkingDay.objects.get(date=self.day2)
        )
        self.assertEqual(total, Decimal("20"))
        self.assertEqual(shortage, Decimal("0"))
        self.assertEqual(overage, Decimal("0"))

    def test_shortage_displayed_when_theoretical_exceeds_actual(self):
        self.client.post(
            f"/inventory/{self.day1}/tank/{self.tank.id}/opening/",
            {"opening_quantity": "1000"},
        )
        self.client.post(
            f"/inventory/{self.day1}/tank/{self.tank.id}/actual/",
            {"actual_inventory": "900"},  # theoretical=1000 -> shortage=100
        )
        resp = self.client.get(f"/inventory/{self.day1}/")
        self.assertContains(resp, "100")

    def test_future_date_inventory_entry_blocked(self):
        resp = self.client.post(
            f"/inventory/2099-01-01/tank/{self.tank.id}/actual/",
            {"actual_inventory": "100"},
            follow=True,
        )
        self.assertContains(resp, "آینده")
        self.assertEqual(TankInventory.objects.count(), 0)

    def test_editing_actual_inventory_does_not_duplicate_row(self):
        self.client.post(
            f"/inventory/{self.day1}/tank/{self.tank.id}/opening/",
            {"opening_quantity": "0"},
        )
        self.client.post(
            f"/inventory/{self.day1}/tank/{self.tank.id}/actual/",
            {"actual_inventory": "100"},
        )
        self.client.post(
            f"/inventory/{self.day1}/tank/{self.tank.id}/actual/",
            {"actual_inventory": "150"},
        )
        self.assertEqual(
            TankInventory.objects.filter(tank=self.tank, working_day__date=self.day1).count(), 1
        )
        self.assertEqual(
            TankInventory.objects.get(tank=self.tank, working_day__date=self.day1).actual_inventory,
            Decimal("150"),
        )


class TanksSectionUiReworkTests(_TestCase):
    """
    Covers the مخازن (Tanks) section rework: "موجودی نظری" renamed to
    "موجودی غیرواقعی" and "اضافه" renamed to "سرک" at the UI level only
    (day_detail.html), and the actual-inventory entry form now also
    displaying the 7 automatically-calculated values that already exist
    in inventory/services.py, using their exact values -- no new
    calculation logic anywhere.
    """

    def setUp(self):
        self.user = User_.objects.create_user(username="op3", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S3", province="P", city="C")
        self.product = Product.objects.create(name="Regular")
        self.tank = Tank.objects.create(station=station, product=self.product, capacity=50000)
        self.client.login(username="op3", password="testpass123")
        self.day1 = "2026-07-23"  # accounting start for an Aug-1 license

    def test_day_detail_shows_renamed_labels(self):
        self.client.post(f"/inventory/{self.day1}/tank/{self.tank.id}/opening/", {"opening_quantity": "0"})
        self.client.post(f"/inventory/{self.day1}/tank/{self.tank.id}/actual/", {"actual_inventory": "0"})
        resp = self.client.get(f"/inventory/{self.day1}/")
        self.assertContains(resp, "موجودی غیرواقعی")
        self.assertContains(resp, "سرک")

    def test_day_detail_does_not_show_old_labels(self):
        self.client.post(f"/inventory/{self.day1}/tank/{self.tank.id}/opening/", {"opening_quantity": "0"})
        self.client.post(f"/inventory/{self.day1}/tank/{self.tank.id}/actual/", {"actual_inventory": "0"})
        resp = self.client.get(f"/inventory/{self.day1}/")
        self.assertNotContains(resp, "موجودی نظری")
        self.assertNotContains(resp, ">اضافه<")

    def test_shortage_still_shown_under_kosri_when_negative_theoretical_gap(self):
        # Opening=1000, no purchase/sale/test, Actual=900 -> theoretical=1000
        # -> shortage=100. The calculation itself is untouched; only the
        # sibling column's label ("سرک") changed.
        self.client.post(f"/inventory/{self.day1}/tank/{self.tank.id}/opening/", {"opening_quantity": "1000"})
        self.client.post(f"/inventory/{self.day1}/tank/{self.tank.id}/actual/", {"actual_inventory": "900"})
        resp = self.client.get(f"/inventory/{self.day1}/")
        self.assertContains(resp, "کسری")
        self.assertContains(resp, "100")

    def test_overage_still_shown_under_sarak_when_actual_exceeds_theoretical(self):
        # Opening=0, Actual=10 -> theoretical=0 -> overage=10, now labeled سرک.
        self.client.post(f"/inventory/{self.day1}/tank/{self.tank.id}/opening/", {"opening_quantity": "0"})
        self.client.post(f"/inventory/{self.day1}/tank/{self.tank.id}/actual/", {"actual_inventory": "10"})
        resp = self.client.get(f"/inventory/{self.day1}/")
        self.assertContains(resp, "سرک")
        self.assertContains(resp, "10")

    def test_entry_form_shows_all_eight_fields_in_order(self):
        self.client.post(f"/inventory/{self.day1}/tank/{self.tank.id}/opening/", {"opening_quantity": "0"})
        resp = self.client.get(f"/inventory/{self.day1}/tank/{self.tank.id}/actual/")
        content = resp.content.decode()
        # Search only within the panel body (after the page heading), and
        # use the field-label <div> wrapper so "موجودی واقعی"/"آزمایش" as
        # standalone labels aren't confused with their appearance inside
        # the heading or inside "بازگشت از آزمایش".
        body = content.split("</h2>", 1)[1]
        labels = [
            "مانده از قبل", "خرید روزانه", "بازگشت از آزمایش", "جمع کل",
            "فروش روزانه", "موجودی غیرواقعی", "آزمایش", "موجودی واقعی",
        ]
        wrapped = [f">{l}<" for l in labels]
        for w in wrapped:
            self.assertIn(w, body)
        positions = [body.index(w) for w in wrapped]
        self.assertEqual(positions, sorted(positions))

    def test_entry_form_shows_correct_values_matching_spec_example(self):
        # Spec §60 worked example (corrected): Opening=1000, Purchase=100, Test=5,
        # Sales=200 -> Total=1105, Theoretical = 1105 - (200 + 5) = 900.
        self.client.post(f"/inventory/{self.day1}/tank/{self.tank.id}/opening/", {"opening_quantity": "1000"})
        working_day = DailyWorkingDay.objects.get(date=self.day1)
        PurchaseInvoice.objects.create(
            working_day=working_day, tank=self.tank, quantity=100, purchase_rate=Decimal("1200"),
        )
        nozzle = Nozzle.objects.create(tank=self.tank, number=1)
        invoice = SalesInvoice.objects.create(working_day=working_day, operator=self.user)
        NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=nozzle,
            previous_meter=Decimal("0"), new_meter=Decimal("205"), test=Decimal("5"),
            sales_rate=Decimal("1200"),
        )

        resp = self.client.get(f"/inventory/{self.day1}/tank/{self.tank.id}/actual/")
        content = resp.content.decode()
        self.assertIn("1,000", content)  # مانده از قبل
        self.assertIn("100", content)   # خرید روزانه
        self.assertIn("5", content)     # بازگشت از آزمایش / آزمایش
        self.assertIn("1,105", content)  # جمع کل
        self.assertIn("200", content)   # فروش روزانه
        self.assertRegex(content, r"موجودی غیرواقعی</div>\s*<div[^>]*>\s*900\s*</div>")   # موجودی غیرواقعی
        self.assertNotIn("905", content)

    def test_first_seven_fields_are_not_form_inputs(self):
        self.client.post(f"/inventory/{self.day1}/tank/{self.tank.id}/opening/", {"opening_quantity": "0"})
        resp = self.client.get(f"/inventory/{self.day1}/tank/{self.tank.id}/actual/")
        content = resp.content.decode()
        # Scope to the <form> element only, since the page (via base.html)
        # also legitimately contains other inputs (the header's global
        # date control). Within the purchase/inventory form itself, only
        # the CSRF token and the one real editable field should be
        # <input> elements -- the 7 locked values must not be.
        form_html = content.split('<form method="post" data-enter-next>', 1)[1].split("</form>", 1)[0]
        self.assertEqual(form_html.count("<input"), 2)  # csrf token + actual_inventory

    def test_editing_an_existing_entry_still_shows_correct_locked_values(self):
        self.client.post(f"/inventory/{self.day1}/tank/{self.tank.id}/opening/", {"opening_quantity": "1000"})
        self.client.post(f"/inventory/{self.day1}/tank/{self.tank.id}/actual/", {"actual_inventory": "1000"})
        # Re-open the same day/tank's form (editing) -- locked values must
        # still reflect the same underlying calculation, unaffected by
        # the fact that an actual_inventory row now exists.
        resp = self.client.get(f"/inventory/{self.day1}/tank/{self.tank.id}/actual/")
        self.assertContains(resp, "1000")
