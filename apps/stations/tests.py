"""
Koohi 118 station configuration: Regular petrol + CNG, 18 nozzles in two
independent groups (regular 1-14, CNG 1-4).
"""

import datetime
import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.core.display import persian_product_name
from apps.license.models import License
from apps.sales.models import NozzleSale, SalesInvoice
from apps.seals.forms import NozzleSealForm
from apps.seals.models import NozzleSeal
from apps.stations.models import Nozzle, Product, Station, Tank
from apps.workday.models import DailyWorkingDay

User = get_user_model()
D = Decimal


class SeededConfigurationTests(TestCase):
    def setUp(self):
        call_command("seed_station", stdout=io.StringIO())

    def test_only_regular_and_cng_products_exist(self):
        self.assertEqual(sorted(Product.objects.values_list("name", flat=True)), ["CNG", "Regular"])
        self.assertFalse(Product.objects.filter(name__icontains="super").exists())
        self.assertEqual(Tank.objects.count(), 2)

    def test_product_display_names(self):
        self.assertEqual(persian_product_name("Regular"), "بنزین معمولی")
        self.assertEqual(persian_product_name("CNG"), "CNG")

    def test_eighteen_nozzles_in_two_independent_groups(self):
        self.assertEqual(Nozzle.objects.count(), 18)
        regular = Nozzle.objects.filter(tank__product__name="Regular")
        cng = Nozzle.objects.filter(tank__product__name="CNG")
        self.assertEqual(sorted(regular.values_list("number", flat=True)), list(range(1, 15)))
        self.assertEqual(sorted(cng.values_list("number", flat=True)), [1, 2, 3, 4])
        # CNG nozzles are never represented as regular nozzles 15-18.
        self.assertFalse(Nozzle.objects.filter(number__gt=14).exists())

    def test_identifiers_and_labels(self):
        self.assertEqual([n.identifier for n in Nozzle.objects.all()],
                         [str(i) for i in range(1, 15)] + [f"CNG {i}" for i in range(1, 5)])
        self.assertEqual([n.label for n in Nozzle.objects.all()][-4:],
                         ["نازل CNG 1", "نازل CNG 2", "نازل CNG 3", "نازل CNG 4"])
        self.assertEqual(Nozzle.objects.get(tank__product__name="Regular", number=7).label, "نازل 7")
        self.assertTrue(all(n.is_cng for n in Nozzle.objects.filter(tank__product__name="CNG")))
        self.assertFalse(any(n.is_cng for n in Nozzle.objects.filter(tank__product__name="Regular")))

    def test_seed_is_idempotent(self):
        call_command("seed_station", stdout=io.StringIO())
        self.assertEqual((Station.objects.count(), Tank.objects.count(), Nozzle.objects.count()), (1, 2, 18))

    def test_tanks_are_ordered_regular_then_cng(self):
        self.assertEqual([t.product.name for t in Tank.objects.select_related("product")], ["Regular", "CNG"])


class CngScreensTests(TestCase):
    """Seal form/list and the sales invoice with the seeded 18-nozzle station."""

    def setUp(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        call_command("seed_station", stdout=io.StringIO())
        self.client.login(username="op1", password="testpass123")

    def test_seal_form_offers_exactly_the_18_nozzles_with_their_labels(self):
        labels = [label for _value, label in NozzleSealForm().fields["nozzle"].choices if _value]
        self.assertEqual(labels, [f"نازل {i}" for i in range(1, 15)] + [f"نازل CNG {i}" for i in range(1, 5)])

    def test_seals_list_orders_regular_before_cng_and_shows_cng_identifier(self):
        cng2 = Nozzle.objects.get(tank__product__name="CNG", number=2)
        reg3 = Nozzle.objects.get(tank__product__name="Regular", number=3)
        reg14 = Nozzle.objects.get(tank__product__name="Regular", number=14)
        for nozzle, num in ((cng2, "S-C"), (reg14, "S-14"), (reg3, "S-3")):
            NozzleSeal.objects.create(nozzle=nozzle, section="flag_door_1", date=datetime.date(2026, 8, 1), seal_number=num)
        resp = self.client.get("/seals/?start_date=2026-08-01&end_date=2026-08-01")
        self.assertEqual([s.seal_number for s in resp.context["seals"]], ["S-3", "S-14", "S-C"])
        html = resp.content.decode()
        self.assertIn("CNG 2", html)
        self.assertNotIn("سوپر", html)

    def test_sales_invoice_detail_and_print_list_cng_rows_after_regular(self):
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))
        inv = SalesInvoice.objects.create(working_day=wd, operator=self.user)
        for nozzle in (Nozzle.objects.get(tank__product__name="CNG", number=1),
                       Nozzle.objects.get(tank__product__name="Regular", number=1)):
            NozzleSale.objects.create(sales_invoice=inv, nozzle=nozzle, previous_meter=D(0), new_meter=D(100),
                                      test=D(0), sales_rate=D(1000))
        resp = self.client.get("/sales/invoices/2026-08-01/")
        self.assertEqual([s.nozzle.identifier for s in resp.context["nozzle_sales"]], ["1", "CNG 1"])
        self.assertContains(resp, "16 نازل ثبت نشده")
        self.assertContains(resp, "بنزین معمولی")
        pdf = self.client.get("/print/sales-invoice/2026-08-01/")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.content[:4], b"%PDF")

    def test_nozzle_ledger_select_lists_cng_nozzles_with_cng_label(self):
        html = self.client.get("/reports/nozzle-ledger/").content.decode()
        for i in range(1, 5):
            self.assertIn(f"نازل CNG {i} (CNG)", html)
        self.assertIn("نازل 14 (بنزین معمولی)", html)
        self.assertNotIn("نازل 15", html)
