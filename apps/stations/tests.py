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

    def test_seal_form_offers_only_the_14_regular_nozzles(self):
        labels = [label for _value, label in NozzleSealForm().fields["nozzle"].choices if _value]
        self.assertEqual(labels, [f"نازل {i}" for i in range(1, 15)])
        html = self.client.get("/seals/new/").content.decode()
        self.assertNotIn("CNG", html)

    def test_cng_nozzles_cannot_be_submitted_or_registered(self):
        cng1 = Nozzle.objects.get(tank__product__name="CNG", number=1)
        data = {"nozzle": cng1.pk, "section": "flag_door_1", "date": "1405/05/10", "seal_number": "X1"}
        resp = self.client.post("/seals/new/", data)
        self.assertEqual(resp.status_code, 200)                       # form re-rendered with an error
        self.assertTrue(resp.context["form"].errors.get("nozzle"))
        self.assertFalse(NozzleSeal.objects.exists())
        # Defense in depth: the model itself refuses a CNG seal.
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            NozzleSeal(nozzle=cng1, section="flag_door_1", date=datetime.date(2026, 8, 1), seal_number="X2").full_clean()

    def test_regular_nozzle_seal_registration_still_works(self):
        reg14 = Nozzle.objects.get(tank__product__name="Regular", number=14)
        resp = self.client.post("/seals/new/", {"nozzle": reg14.pk, "section": "flag_door_1",
                                                "date": "1405/05/10", "seal_number": "R14"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(NozzleSeal.objects.get().nozzle, reg14)

    def test_stray_cng_seals_are_never_listed_printed_or_editable(self):
        cng2 = Nozzle.objects.get(tank__product__name="CNG", number=2)
        reg3 = Nozzle.objects.get(tank__product__name="Regular", number=3)
        reg14 = Nozzle.objects.get(tank__product__name="Regular", number=14)
        NozzleSeal.objects.bulk_create([    # bypasses validation: historical/stray data
            NozzleSeal(nozzle=cng2, section="flag_door_1", date=datetime.date(2026, 8, 1), seal_number="S-C"),
            NozzleSeal(nozzle=reg14, section="flag_door_1", date=datetime.date(2026, 8, 1), seal_number="S-14"),
            NozzleSeal(nozzle=reg3, section="flag_door_1", date=datetime.date(2026, 8, 1), seal_number="S-3"),
        ])
        resp = self.client.get("/seals/?start_date=2026-08-01&end_date=2026-08-01")
        self.assertEqual([s.seal_number for s in resp.context["seals"]], ["S-3", "S-14"])
        self.assertNotIn("CNG", resp.content.decode())
        stray = NozzleSeal.objects.get(seal_number="S-C")
        for url in (f"/seals/{stray.pk}/edit/", f"/seals/{stray.pk}/delete/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        pdf = self.client.get("/print/seals/?start_date=2026-08-01&end_date=2026-08-01")
        self.assertEqual(pdf.status_code, 200)
        try:
            from pypdf import PdfReader
        except ImportError:                       # pragma: no cover
            return
        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf.content)).pages)
        self.assertNotIn("CNG", text)
        self.assertIn("S-14", text)

    def test_sales_invoice_detail_and_print_list_cng_rows_after_regular(self):
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))
        inv = SalesInvoice.objects.create(working_day=wd, operator=self.user)
        for nozzle in (Nozzle.objects.get(tank__product__name="CNG", number=1),
                       Nozzle.objects.get(tank__product__name="Regular", number=1)):
            NozzleSale.objects.create(sales_invoice=inv, nozzle=nozzle, previous_meter=D(0), new_meter=D(100),
                                      test=D(0), sales_rate=D(1000))
        resp = self.client.get("/sales/invoices/2026-08-01/")
        self.assertEqual([s.nozzle.identifier for s in resp.context["nozzle_sales"]], ["1"])
        self.assertContains(resp, "16 نازل ثبت نشده")
        self.assertContains(resp, "بنزین معمولی")
        cng = self.client.get("/sales/invoices/2026-08-01/?product=CNG")
        self.assertEqual([s.nozzle.identifier for s in cng.context["nozzle_sales"]], ["CNG 1"])
        for query in ("", "?product=CNG"):
            pdf = self.client.get("/print/sales-invoice/2026-08-01/" + query)
            self.assertEqual(pdf.status_code, 200)
            self.assertEqual(pdf.content[:4], b"%PDF")

    def test_nozzle_ledger_select_lists_cng_nozzles_with_cng_label(self):
        html = self.client.get("/reports/nozzle-ledger/").content.decode()
        for i in range(1, 5):
            self.assertIn(f"نازل CNG {i} (CNG)", html)
        self.assertIn("نازل 14 (بنزین معمولی)", html)
        self.assertNotIn("نازل 15", html)


class InventorySectionsExcludeCngTests(TestCase):
    """
    CNG has no purchase invoices and no tank inventory: it must be absent
    from فاکتورهای خرید, دفتر موجودی و عملیات, صورت وضعیت ماهانه, مقایسه
    سیستم مکانیکی و دیجیتال, موجودی مخازن and گزارش ماهانه مخازن (screens,
    URLs and PDFs) -- even if stray rows exist on the CNG tank -- while
    staying available on the sales side.
    """

    DATE = "2026-08-01"

    def setUp(self):
        from django.urls import reverse
        from apps.inventory.models import OpeningInventory, TankInventory
        from apps.purchases.models import PurchaseInvoice

        self.reverse = reverse
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        call_command("seed_station", stdout=io.StringIO())
        self.regular = Tank.objects.get(product__name="Regular")
        self.cng = Tank.objects.get(product__name="CNG")
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))
        inv = SalesInvoice.objects.create(working_day=wd, operator=self.user)
        for nozzle in Nozzle.objects.all():
            NozzleSale.objects.create(sales_invoice=inv, nozzle=nozzle, previous_meter=D(0), new_meter=D(100),
                                      test=D(0), sales_rate=D(1000))
        for tank in (self.regular, self.cng):          # stray CNG rows must never surface
            OpeningInventory.objects.create(tank=tank, opening_quantity=D(500), effective_month=datetime.date(2026, 7, 23))
            PurchaseInvoice.objects.create(working_day=wd, tank=tank, quantity=1000, purchase_rate=D(4000))
            TankInventory.objects.create(working_day=wd, tank=tank, actual_inventory=D(1200))
        self.client.login(username="op1", password="testpass123")

    def pdf_text(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, url)
        self.assertEqual(resp.content[:4], b"%PDF", url)
        try:
            from pypdf import PdfReader
        except ImportError:                       # pragma: no cover
            self.skipTest("pypdf not installed")
        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(resp.content)).pages)

    def test_inventory_tracked_queryset_is_regular_only(self):
        self.assertEqual(list(Tank.objects.inventory_tracked()), [self.regular])
        self.assertTrue(self.regular.tracks_inventory)
        self.assertFalse(self.cng.tracks_inventory)

    def test_purchases_screen_and_entry_urls(self):
        html = self.client.get("/purchases/?start_date=2026-08-01&end_date=2026-08-01").content.decode()
        self.assertIn("بنزین معمولی", html)
        self.assertNotIn("CNG", html)
        self.assertIn(f"/tank/{self.regular.id}/new/", html)
        self.assertNotIn(f"/tank/{self.cng.id}/new/", html)
        url = self.reverse("purchases:purchase_entry", args=[self.DATE, self.cng.id])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"quantity": 1, "purchase_rate": "1"}).status_code, 404)
        self.assertEqual(self.client.get(self.reverse("purchases:purchase_entry", args=[self.DATE, self.regular.id])).status_code, 200)

    def test_inventory_screens_and_urls(self):
        resp = self.client.get(self.reverse("inventory:day_detail", args=[self.DATE]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r["tank"] for r in resp.context["rows"]], [self.regular])
        self.assertNotIn("CNG", resp.content.decode())
        for name in ("inventory:actual_inventory_entry", "inventory:opening_inventory_entry"):
            self.assertEqual(self.client.get(self.reverse(name, args=[self.DATE, self.cng.id])).status_code, 404, name)
        self.assertEqual(self.client.get(self.reverse("inventory:actual_inventory_entry", args=[self.DATE, self.regular.id])).status_code, 200)
        # (the opening-inventory form only opens on the first accounting day, otherwise it redirects -- never 404 for Regular)
        self.assertNotEqual(self.client.get(self.reverse("inventory:opening_inventory_entry", args=[self.DATE, self.regular.id])).status_code, 404)

    def test_statement_and_comparison_have_no_cng_rows(self):
        from apps.comparison.services import build_digital_rows, build_mechanical_rows
        from apps.statement.services import build_statement_rows

        self.assertEqual([r["product"].name for r in build_statement_rows(1405, 5)], ["Regular"])
        self.assertEqual([r["product"].name for r in build_mechanical_rows(1405, 5)], ["Regular"])
        self.assertEqual([r["product"].name for r in build_digital_rows(1405, 5)], ["Regular"])
        for url in ("/statement/?year=1405&month=5", "/comparison/?year=1405&month=5"):
            html = self.client.get(url).content.decode()
            self.assertIn("بنزین معمولی", html)
            self.assertNotIn("CNG", html, url)
        from apps.comparison.models import DigitalEntry
        self.assertFalse(DigitalEntry.objects.filter(tank=self.cng).exists())

    def test_tank_reports_have_no_cng(self):
        for url in ("/reports/petroleum-ledger/", f"/reports/petroleum-ledger/?tank_id={self.regular.id}&start_date=2026-08-01&end_date=2026-08-01",
                    "/reports/petroleum-monthly/?year=1405&month=5"):
            html = self.client.get(url).content.decode()
            self.assertNotIn("CNG", html, url)
        self.assertEqual(self.client.get(f"/reports/petroleum-ledger/?tank_id={self.cng.id}&start_date=2026-08-01&end_date=2026-08-01").status_code, 404)
        self.assertEqual(self.client.get(f"/print/petroleum-ledger/{self.cng.id}/?start_date=2026-08-01&end_date=2026-08-01").status_code, 404)

    def test_pdfs_of_the_six_sections_have_no_cng(self):
        urls = [
            "/print/purchases-ledger/?start_date=2026-08-01&end_date=2026-08-02",
            f"/print/petroleum-ledger/{self.regular.id}/?start_date=2026-08-01&end_date=2026-08-02",
            "/print/petroleum-monthly/?year=1405&month=5",
            "/print/statement/?year=1405&month=5",
            "/print/comparison/?year=1405&month=5",
        ]
        for url in urls:
            text = self.pdf_text(url)
            self.assertNotIn("CNG", text, url)
            self.assertNotIn("سوپر", text, url)

    def test_cng_stays_available_on_the_sales_side(self):
        sales = self.client.get("/sales/invoices/2026-08-01/?product=CNG")
        self.assertEqual([s.nozzle.identifier for s in sales.context["nozzle_sales"]], ["CNG 1", "CNG 2", "CNG 3", "CNG 4"])
        report = self.client.get(f"/reports/all-nozzles/?year=1405&month=5&tank_id={self.cng.id}")
        self.assertEqual(report.status_code, 200)
        self.assertContains(report, "CNG 1")
        self.assertEqual(self.client.get(f"/print/all-nozzles/?year=1405&month=5&tank_id={self.cng.id}").status_code, 200)
        self.assertContains(self.client.get("/"), "CNG 4")


class ProductSeparatedSalesInvoiceTests(TestCase):
    """
    فاکتورهای فروش: the daily invoice is DISPLAYED (and printed) one product
    at a time, while data entry stays one sequential flow over all 18 nozzles.
    """

    DATE = "2026-08-01"

    def setUp(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        call_command("seed_station", stdout=io.StringIO())
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))
        inv = SalesInvoice.objects.create(working_day=wd, operator=self.user)
        # Regular nozzle n sells n*10 at rate 1000; CNG nozzle n sells n*100 at rate 500.
        for nozzle in Nozzle.objects.all():
            cng = nozzle.is_cng
            NozzleSale.objects.create(
                sales_invoice=inv, nozzle=nozzle, previous_meter=D(0),
                new_meter=D(nozzle.number * (100 if cng else 10)), test=D(0),
                sales_rate=D(500 if cng else 1000),
            )
        self.client.login(username="op1", password="testpass123")

    def page(self, query=""):
        return self.client.get(f"/sales/invoices/{self.DATE}/{query}")

    def identifiers(self, resp):
        return [s.nozzle.identifier for s in resp.context["nozzle_sales"]]

    def pdf_text(self, query=""):
        resp = self.client.get(f"/print/sales-invoice/{self.DATE}/{query}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content[:4], b"%PDF")
        try:
            from pypdf import PdfReader
        except ImportError:                       # pragma: no cover
            self.skipTest("pypdf not installed")
        return resp, "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(resp.content)).pages)

    def test_default_view_is_regular_petrol_only(self):
        resp = self.page()
        self.assertEqual(self.identifiers(resp), [str(n) for n in range(1, 15)])
        self.assertEqual(resp.context["selected_product"].name, "Regular")
        html = resp.content.decode()
        self.assertNotIn("CNG 1", html.split("</thead>", 1)[1])      # no CNG row in the table body
        self.assertEqual(resp.context["totals"]["nozzle_count"], 14)

    def test_cng_view_shows_only_the_four_cng_nozzles(self):
        resp = self.page("?product=CNG")
        self.assertEqual(self.identifiers(resp), ["CNG 1", "CNG 2", "CNG 3", "CNG 4"])
        body = resp.content.decode().split("</thead>", 1)[1]
        self.assertNotIn("<td style=\"padding: 0.5rem;\" class=\"numeric\">5</td>", body)
        self.assertEqual(resp.context["totals"]["nozzle_count"], 4)

    def test_product_switch_offers_exactly_the_two_products(self):
        html = self.page().content.decode()
        self.assertIn('data-product="Regular"', html)
        self.assertIn('data-product="CNG"', html)
        self.assertEqual(html.count('role="tab"'), 2)
        self.assertIn('aria-selected="true"', html)
        self.assertNotIn("سوپر", html)

    def test_unknown_product_falls_back_to_regular(self):
        self.assertEqual(self.page("?product=Nonsense").context["selected_product"].name, "Regular")

    def test_totals_follow_the_selected_product(self):
        regular = self.page().context["totals"]
        cng = self.page("?product=CNG").context["totals"]
        self.assertEqual(regular["total_operation"], D(sum(n * 10 for n in range(1, 15))))
        self.assertEqual(regular["total_amount"], D(sum(n * 10 for n in range(1, 15)) * 1000))
        self.assertEqual(cng["total_operation"], D(sum(n * 100 for n in range(1, 5))))
        self.assertEqual(cng["total_amount"], D(sum(n * 100 for n in range(1, 5)) * 500))

    def test_each_pdf_contains_only_its_products_rows(self):
        resp, regular_text = self.pdf_text()
        self.assertIn("filename=\"sales-invoice-2026-08-01-regular.pdf\"", resp["Content-Disposition"])
        self.assertIn("بنزین معمولی", regular_text)
        self.assertNotIn("CNG", regular_text)
        resp, cng_text = self.pdf_text("?product=CNG")
        self.assertIn("filename=\"sales-invoice-2026-08-01-cng.pdf\"", resp["Content-Disposition"])
        for i in range(1, 5):
            self.assertIn(f"CNG {i}", cng_text)
        self.assertNotIn("بنزین معمولی", cng_text)

    def test_pdf_rows_match_the_table_for_each_product(self):
        from django.template.loader import render_to_string
        from apps.printing.services import build_sales_invoice_context

        wd = DailyWorkingDay.objects.get(date=datetime.date(2026, 8, 1))
        for name in ("Regular", "CNG"):
            screen = self.page(f"?product={name}")
            context = build_sales_invoice_context(wd, name)
            self.assertEqual([s.pk for s in context["nozzle_sales"]], [s.pk for s in screen.context["nozzle_sales"]])
            self.assertEqual(context["totals"], screen.context["totals"])
            html = render_to_string("printing/sales_invoice_print.html", context)
            self.assertEqual(html.count("<tr>") - 3, len(screen.context["nozzle_sales"]))   # minus 3 rows: totals header + body, table header

    def test_print_button_and_edit_links_follow_the_selected_product(self):
        html = self.page("?product=CNG").content.decode()
        self.assertIn("/print/sales-invoice/2026-08-01/?product=CNG", html)
        self.assertIn("?product=CNG\">ویرایش</a>", html)

    def test_data_entry_is_still_one_sequential_flow_over_all_18_nozzles(self):
        SalesInvoice.objects.all().delete()                   # a fresh, empty day
        regular = list(Nozzle.objects.filter(tank__product__name="Regular"))
        cng = list(Nozzle.objects.filter(tank__product__name="CNG"))
        seq = regular + cng
        resp = self.client.get(f"/sales/invoices/{self.DATE}/nozzle/")
        self.assertRedirects(resp, f"/sales/invoices/{self.DATE}/nozzle/{seq[0].pk}/")
        for nozzle, following in zip(seq, seq[1:]):
            resp = self.client.post(f"/sales/invoices/{self.DATE}/nozzle/{nozzle.pk}/",
                                    {"previous_meter": "0", "new_meter": "5", "test": "0", "sales_rate": "1000"})
            self.assertRedirects(resp, f"/sales/invoices/{self.DATE}/nozzle/{following.pk}/")
        last = self.client.post(f"/sales/invoices/{self.DATE}/nozzle/{seq[-1].pk}/",
                                {"previous_meter": "0", "new_meter": "5", "test": "0", "sales_rate": "1000"})
        self.assertRedirects(last, f"/sales/invoices/{self.DATE}/")
        self.assertEqual(NozzleSale.objects.count(), 18)

    def test_editing_returns_to_the_product_table_being_viewed(self):
        cng1 = Nozzle.objects.get(tank__product__name="CNG", number=1)
        resp = self.client.post(f"/sales/invoices/{self.DATE}/nozzle/{cng1.pk}/?product=CNG",
                                {"previous_meter": "0", "new_meter": "7", "test": "0", "sales_rate": "500"})
        self.assertRedirects(resp, f"/sales/invoices/{self.DATE}/?product=CNG")


class CngHasNoTestFieldTests(TestCase):
    """
    «تست» is removed for CNG only: entry form, stored value, calculations,
    on-screen table and PDF. Regular petrol is unchanged everywhere.
    """

    DATE = "2026-08-01"

    def setUp(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        call_command("seed_station", stdout=io.StringIO())
        self.regular1 = Nozzle.objects.get(tank__product__name="Regular", number=1)
        self.cng1 = Nozzle.objects.get(tank__product__name="CNG", number=1)
        self.client.login(username="op1", password="testpass123")

    def entry(self, nozzle):
        return f"/sales/invoices/{self.DATE}/nozzle/{nozzle.pk}/"

    def test_regular_entry_form_keeps_the_test_field(self):
        html = self.client.get(self.entry(self.regular1)).content.decode()
        self.assertIn('name="test"', html)
        self.assertIn("تست", html)

    def test_cng_entry_form_has_no_test_field(self):
        resp = self.client.get(self.entry(self.cng1))
        html = resp.content.decode()
        self.assertNotIn('name="test"', html)
        self.assertNotIn("تست", html)
        self.assertEqual(list(resp.context["form"].fields), ["previous_meter", "new_meter", "sales_rate"])
        for label in ("کنتور قبلی", "کنتور جدید", "نرخ فروش"):
            self.assertIn(label, html)

    def test_cng_can_be_saved_with_only_meters_and_rate(self):
        resp = self.client.post(self.entry(self.cng1), {"previous_meter": "100", "new_meter": "350", "sales_rate": "500"})
        self.assertEqual(resp.status_code, 302)
        sale = NozzleSale.objects.get(nozzle=self.cng1)
        self.assertEqual((sale.test, sale.operation, sale.mechanical_sales, sale.total_amount),
                         (D(0), D(250), D(250), D(125000)))

    def test_a_submitted_test_value_is_ignored_for_cng(self):
        self.client.post(self.entry(self.cng1), {"previous_meter": "0", "new_meter": "100", "test": "40", "sales_rate": "500"})
        sale = NozzleSale.objects.get(nozzle=self.cng1)
        self.assertEqual((sale.test, sale.mechanical_sales), (D(0), D(100)))

    def test_cng_sales_always_store_zero_test_even_if_set_in_code(self):
        inv = SalesInvoice.objects.create(working_day=DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1)), operator=self.user)
        sale = NozzleSale.objects.create(sales_invoice=inv, nozzle=self.cng1, previous_meter=D(0), new_meter=D(100), test=D(40), sales_rate=D(500))
        sale.refresh_from_db()
        self.assertEqual((sale.test, sale.mechanical_sales), (D(0), D(100)))

    def test_regular_calculation_still_subtracts_the_test(self):
        resp = self.client.post(self.entry(self.regular1), {"previous_meter": "0", "new_meter": "100", "test": "5", "sales_rate": "1000"})
        self.assertEqual(resp.status_code, 302)
        sale = NozzleSale.objects.get(nozzle=self.regular1)
        self.assertEqual((sale.test, sale.operation, sale.mechanical_sales, sale.total_amount),
                         (D(5), D(100), D(95), D(95000)))

    def test_regular_entry_still_requires_the_test_field(self):
        resp = self.client.post(self.entry(self.regular1), {"previous_meter": "0", "new_meter": "100", "sales_rate": "1000"})
        self.assertEqual(resp.status_code, 200)                       # re-rendered with the form error
        self.assertTrue(resp.context["form"].errors)
        self.assertFalse(NozzleSale.objects.filter(nozzle=self.regular1).exists())

    def test_sequential_entry_asks_test_only_for_the_regular_nozzles(self):
        regular = list(Nozzle.objects.filter(tank__product__name="Regular"))
        cng = list(Nozzle.objects.filter(tank__product__name="CNG"))
        for nozzle in regular:
            page = self.client.get(self.entry(nozzle))
            self.assertIn('name="test"', page.content.decode(), nozzle.identifier)
            self.client.post(self.entry(nozzle), {"previous_meter": "0", "new_meter": "10", "test": "1", "sales_rate": "1000"})
        for index, nozzle in enumerate(cng):
            page = self.client.get(self.entry(nozzle))
            self.assertNotIn('name="test"', page.content.decode(), nozzle.identifier)
            resp = self.client.post(self.entry(nozzle), {"previous_meter": "0", "new_meter": "10", "sales_rate": "500"})
            if index < 3:
                self.assertRedirects(resp, self.entry(cng[index + 1]))
            else:
                self.assertRedirects(resp, f"/sales/invoices/{self.DATE}/")
        self.assertEqual(NozzleSale.objects.count(), 18)

    def _filled_day(self):
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))
        inv = SalesInvoice.objects.create(working_day=wd, operator=self.user)
        for nozzle in Nozzle.objects.all():
            NozzleSale.objects.create(sales_invoice=inv, nozzle=nozzle, previous_meter=D(0), new_meter=D(100),
                                      test=D(7), sales_rate=D(1000))        # CNG's 7 is dropped on save
        return wd

    def test_tables_regular_has_test_column_cng_does_not(self):
        self._filled_day()
        regular = self.client.get(f"/sales/invoices/{self.DATE}/").content.decode()
        cng = self.client.get(f"/sales/invoices/{self.DATE}/?product=CNG").content.decode()
        self.assertEqual(regular.count("<th style=\"padding: 0.5rem;\">تست</th>"), 1)
        self.assertIn("مجموع تست", regular)
        self.assertNotIn("تست", cng)
        self.assertIn("کنتور قبلی", cng)
        self.assertIn("کنتور جدید", cng)
        self.assertIn("نرخ", cng)

    def test_pdfs_regular_has_test_column_cng_does_not(self):
        self._filled_day()
        from django.template.loader import render_to_string
        from apps.printing.services import build_sales_invoice_context

        wd = DailyWorkingDay.objects.get(date=datetime.date(2026, 8, 1))
        regular_html = render_to_string("printing/sales_invoice_print.html", build_sales_invoice_context(wd, "Regular"))
        cng_html = render_to_string("printing/sales_invoice_print.html", build_sales_invoice_context(wd, "CNG"))
        self.assertIn("<th>تست</th>", regular_html)
        self.assertIn("<th>مجموع تست</th>", regular_html)
        self.assertNotIn("تست", cng_html)
        try:
            from pypdf import PdfReader
        except ImportError:                       # pragma: no cover
            self.skipTest("pypdf not installed")
        for query, expect_test in (("", True), ("?product=CNG", False)):
            resp = self.client.get(f"/print/sales-invoice/{self.DATE}/{query}")
            text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(resp.content)).pages)
            self.assertEqual("تست" in text, expect_test, query)

    def test_cng_totals_have_no_test_component(self):
        self._filled_day()
        totals = self.client.get(f"/sales/invoices/{self.DATE}/?product=CNG").context["totals"]
        self.assertEqual((totals["total_test"], totals["total_operation"], totals["total_sales"]), (D(0), D(400), D(400)))
        regular = self.client.get(f"/sales/invoices/{self.DATE}/").context["totals"]
        self.assertEqual((regular["total_test"], regular["total_operation"], regular["total_sales"]), (D(98), D(1400), D(1302)))


class CngNozzleReportsHaveNoTestTests(TestCase):
    """«آزمایش» (test) is removed for CNG in «گزارش کارکرد هر نازل» and
    «لیست اطلاعات فروش» -- screens and PDFs -- and kept for regular petrol."""

    def setUp(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        call_command("seed_station", stdout=io.StringIO())
        self.reg = Nozzle.objects.get(tank__product__name="Regular", number=5)
        self.cng = Nozzle.objects.get(tank__product__name="CNG", number=2)
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))
        inv = SalesInvoice.objects.create(working_day=wd, operator=self.user)
        for nozzle in (self.reg, self.cng):
            NozzleSale.objects.create(sales_invoice=inv, nozzle=nozzle, previous_meter=D(0), new_meter=D(200),
                                      test=D(10), sales_rate=D(1000))       # CNG's 10 is dropped on save
        self.client.login(username="op1", password="testpass123")

    def pdf_text(self, url):
        from pypdf import PdfReader
        resp = self.client.get(url)
        self.assertEqual((resp.status_code, resp.content[:4]), (200, b"%PDF"), url)
        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(resp.content)).pages)

    def test_nozzle_ledger_screen(self):
        q = "&start_date=2026-08-01&end_date=2026-08-02"
        cng = self.client.get(f"/reports/nozzle-ledger/?nozzle_id={self.cng.id}{q}").content.decode()
        reg = self.client.get(f"/reports/nozzle-ledger/?nozzle_id={self.reg.id}{q}").content.decode()
        self.assertNotIn("آزمایش", cng)
        for header in ("کنتور قبلی", "فروش مکانیکی", "کنتور جدید", "نرخ"):
            self.assertIn(header, cng)
        self.assertEqual(cng.split('id="nozzle-ledger-table"', 1)[1].split("</thead>", 1)[0].count("<th "), 7)
        self.assertIn("آزمایش", reg)
        self.assertEqual(reg.split('id="nozzle-ledger-table"', 1)[1].split("</thead>", 1)[0].count("<th "), 8)

    def test_nozzle_ledger_pdf(self):
        q = "?start_date=2026-08-01&end_date=2026-08-02"
        self.assertNotIn("آزمایش", self.pdf_text(f"/print/nozzle-ledger/{self.cng.id}/{q}"))
        self.assertIn("آزمایش", self.pdf_text(f"/print/nozzle-ledger/{self.reg.id}/{q}"))

    def test_all_nozzles_screen_and_pdf(self):
        cng_tank, reg_tank = self.cng.tank, self.reg.tank
        cng = self.client.get(f"/reports/all-nozzles/?year=1405&month=5&tank_id={cng_tank.id}").content.decode()
        reg = self.client.get(f"/reports/all-nozzles/?year=1405&month=5&tank_id={reg_tank.id}").content.decode()
        self.assertNotIn("آزمایش", cng)
        self.assertNotIn('data-total="test"', cng)
        self.assertIn("آزمایش", reg)
        self.assertIn('data-total="test"', reg)
        self.assertNotIn("آزمایش", self.pdf_text(f"/print/all-nozzles/?year=1405&month=5&tank_id={cng_tank.id}"))
        self.assertIn("آزمایش", self.pdf_text(f"/print/all-nozzles/?year=1405&month=5&tank_id={reg_tank.id}"))
