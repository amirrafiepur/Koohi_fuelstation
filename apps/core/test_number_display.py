"""
Task 1 (number formatting) end-to-end verification.

Renders representative on-screen sections AND every printable PDF with a
dataset that mixes whole numbers stored as "X.00" with genuinely
fractional values, then checks the *displayed* output only. Stored
values and calculation logic are never touched by this feature, so these
tests assert on rendered output, not on the database.
"""

import datetime
import io
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.comparison.models import DigitalEntry
from apps.deposits.models import Deposit
from apps.inventory.models import OpeningInventory, TankInventory
from apps.license.models import License
from apps.purchases.models import PurchaseInvoice
from apps.sales.models import NozzleSale, SalesInvoice
from apps.seals.models import NozzleSeal
from apps.statement.models import StatementEntry
from apps.stations.models import Nozzle, Product, Station, Tank
from apps.workday.models import DailyWorkingDay

User = get_user_model()

# A decimal tail ending in zero, e.g. "35.00", "1.50", "1,234.50".
TRAILING_ZERO = re.compile(r"\d\.\d*0(?!\d)")
# A thousands-grouped or plain number with an optional fractional tail.
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def pdf_text(pdf_bytes):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(p.extract_text() for p in reader.pages)


def render_pdf_with_html(client, url):
    """GET a print URL and also capture the exact HTML handed to
    WeasyPrint, so formatting can be asserted on real cells (PDF text
    extraction glues adjacent table cells together and can't be used to
    tell where one number ends and the next begins)."""
    from unittest import mock
    from django.template.loader import render_to_string as real_render

    captured = {}

    def spy(template_name, context=None, *a, **kw):
        out = real_render(template_name, context, *a, **kw)
        captured["html"] = out
        return out

    with mock.patch("apps.printing.views.render_to_string", side_effect=spy):
        resp = client.get(url)
    return resp, captured.get("html", "")


def numeric_cells(html):
    """Text of every element rendered with class="numeric"."""
    return [
        re.sub(r"\s+", " ", m).strip()
        for m in re.findall(r'class="[^"]*numeric[^"]*"[^>]*>([^<]*)<', html)
    ]


class NumberDisplayFixtureMixin:
    def build_data(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="140 Jahan Pour", province="Razavi Khorasan", city="Mashhad")
        self.regular = Product.objects.create(name="Regular")
        self.super = Product.objects.create(name="Super")
        self.rtank = Tank.objects.create(station=station, product=self.regular, capacity=50000)
        self.stank = Tank.objects.create(station=station, product=self.super, capacity=30000)
        self.n1 = Nozzle.objects.create(tank=self.rtank, number=1)
        self.n2 = Nozzle.objects.create(tank=self.stank, number=19)
        self.client.login(username="op1", password="testpass123")

        self.d1 = datetime.date(2026, 8, 1)   # Jalali 1405/05/10
        wd = DailyWorkingDay.objects.create(date=self.d1)
        for tank, qty in ((self.rtank, "123456"), (self.stank, "2000")):
            OpeningInventory.objects.create(
                tank=tank, opening_quantity=Decimal("1000000"), effective_month=datetime.date(2026, 7, 23)
            )
            PurchaseInvoice.objects.create(
                working_day=wd, tank=tank, quantity=Decimal(qty), purchase_rate=Decimal("1200.50"),
                program_number="9001234", tanker_number="55Ab123",
            )
        inv = SalesInvoice.objects.create(working_day=wd, operator=self.user)
        # Mechanical sales 1234567.00 - whole number stored with .00;
        # nozzle 2 has genuinely fractional meters.
        NozzleSale.objects.create(sales_invoice=inv, nozzle=self.n1, previous_meter=Decimal("100000"),
                                  new_meter=Decimal("1334572"), test=Decimal("5"), sales_rate=Decimal("1200"))
        NozzleSale.objects.create(sales_invoice=inv, nozzle=self.n2, previous_meter=Decimal("100.50"),
                                  new_meter=Decimal("1234.75"), test=Decimal("0.25"), sales_rate=Decimal("1500.5"))
        TankInventory.objects.create(tank=self.rtank, working_day=wd, actual_inventory=Decimal("987654.50"))
        TankInventory.objects.create(tank=self.stank, working_day=wd, actual_inventory=Decimal("900000"))
        Deposit.objects.create(date=self.d1, year=1405, month=5, decade=Deposit.FIRST_DECADE,
                               deposit_amount=Decimal("1500000"), difference_amount=Decimal("250.50"),
                               document_number="D-100200")
        NozzleSeal.objects.create(nozzle=self.n1, section=NozzleSeal.SECTION_CHOICES[0][0],
                                  date=self.d1, seal_number="1234567")

    def screens(self):
        return {
            "sales_invoice": f"/sales/invoices/{self.d1.isoformat()}/",
            "sales_list": "/sales/invoices/",
            "purchases_list": "/purchases/?start_date=2026-07-23&end_date=2026-08-01",
            "inventory_day": f"/inventory/{self.d1.isoformat()}/",
            "inventory_actual": f"/inventory/{self.d1.isoformat()}/tank/{self.rtank.id}/actual/",
            "nozzle_ledger": f"/reports/nozzle-ledger/?nozzle_id={self.n2.id}&start_date=2026-07-23&end_date=2026-08-01",
            "all_nozzles": "/reports/all-nozzles/?year=1405&month=5",
            "nozzle_monthly": "/reports/nozzle-monthly/?year=1405&month=5",
            "petroleum_ledger": f"/reports/petroleum-ledger/?tank_id={self.rtank.id}&start_date=2026-07-23&end_date=2026-08-01",
            "petroleum_monthly": "/reports/petroleum-monthly/?year=1405&month=5",
            "deposits": "/deposits/?year=1405&month=5",
            "deposit_decade": "/deposits/1405/5/first/",
            "statement": "/statement/?year=1405&month=5",
            "comparison": "/comparison/?year=1405&month=5",
        }

    def prints(self):
        return {
            "sales_invoice": f"/print/sales-invoice/{self.d1.isoformat()}/",
            "nozzle_ledger": f"/print/nozzle-ledger/{self.n2.id}/?start_date=2026-07-23&end_date=2026-08-01",
            "all_nozzles": "/print/all-nozzles/?year=1405&month=5",
            "nozzle_monthly": "/print/nozzle-monthly/?year=1405&month=5",
            "petroleum_ledger": f"/print/petroleum-ledger/{self.rtank.id}/?start_date=2026-07-23&end_date=2026-08-01",
            "petroleum_monthly": "/print/petroleum-monthly/?year=1405&month=5",
            "purchases_ledger": "/print/purchases-ledger/?start_date=2026-07-23&end_date=2026-08-01",
            "deposit_decade": "/print/deposits-decade/?year=1405&month=5&decade=first",
            "statement": "/print/statement/?year=1405&month=5",
            "comparison": "/print/comparison/?year=1405&month=5",
        }


class TrimZerosEverywhereTests(NumberDisplayFixtureMixin, TestCase):
    """Task 1 Part A."""

    def setUp(self):
        self.build_data()

    def test_screens_render_and_have_no_trailing_zero_decimals(self):
        for name, url in self.screens().items():
            resp = self.client.get(url, follow=True)
            self.assertEqual(resp.status_code, 200, f"{name}: {url}")
            cells = numeric_cells(resp.content.decode())
            for cell in cells:
                self.assertFalse(TRAILING_ZERO.search(cell), f"{name}: {cell!r}")

    def test_pdfs_render_and_have_no_trailing_zero_decimals(self):
        for name, url in self.prints().items():
            resp, html = render_pdf_with_html(self.client, url)
            self.assertEqual(resp.status_code, 200, f"{name}: {url}")
            self.assertTrue(resp.content.startswith(b"%PDF"), name)
            cells = numeric_cells(html)
            self.assertTrue(cells, f"{name}: no numeric cells captured")
            for cell in cells:
                self.assertFalse(TRAILING_ZERO.search(cell), f"{name}: {cell!r}")

    def test_fractional_values_are_preserved(self):
        html = self.client.get(self.screens()["nozzle_ledger"]).content.decode()
        joined = " ".join(numeric_cells(html))
        for expected in ("100.5", "1234.75", "0.25"):
            self.assertIn(expected.replace(",", ""), joined.replace(",", ""))
        text = pdf_text(self.client.get(self.prints()["nozzle_ledger"]).content)
        self.assertIn("1234.75", text.replace(",", ""))

    def test_whole_numbers_lose_the_decimal_tail(self):
        html = self.client.get(self.screens()["deposits"]).content.decode()
        cells = [c.replace(",", "") for c in numeric_cells(html)]
        self.assertIn("1500000", cells)
        self.assertNotIn("1500000.00", cells)

    def test_stored_values_are_unchanged(self):
        self.assertEqual(NozzleSale.objects.get(nozzle=self.n2).new_meter, Decimal("1234.75"))
        self.assertEqual(Deposit.objects.get().deposit_amount, Decimal("1500000.00"))


GROUPED_OK = re.compile(r"^-?\d{1,3}(,\d{3})*(\.\d+)?$")
UNGROUPED_BIG = re.compile(r"(?<![\d.,/-])\d{4,}(?![\d/])")


class ThousandsSeparatorEverywhereTests(NumberDisplayFixtureMixin, TestCase):
    """Task 1 Part B (Part A's rules must still hold on top)."""

    def setUp(self):
        self.build_data()

    def _check_cells(self, name, html):
        cells = numeric_cells(html)
        self.assertTrue(cells, f"{name}: no numeric cells")
        for cell in cells:
            self.assertFalse(TRAILING_ZERO.search(cell), f"{name}: {cell!r}")
            if re.fullmatch(r"-?[\d,]+(\.\d+)?", cell):
                self.assertRegex(cell, GROUPED_OK, f"{name}: {cell!r}")
                self.assertFalse(UNGROUPED_BIG.search(cell), f"{name}: {cell!r}")
        return cells

    def test_screens_group_every_numeric_cell(self):
        for name, url in self.screens().items():
            resp = self.client.get(url, follow=True)
            self.assertEqual(resp.status_code, 200, f"{name}: {url}")
            self._check_cells(name, resp.content.decode())

    def test_pdfs_group_every_numeric_cell(self):
        for name, url in self.prints().items():
            resp, html = render_pdf_with_html(self.client, url)
            self.assertEqual(resp.status_code, 200, f"{name}: {url}")
            self.assertTrue(resp.content.startswith(b"%PDF"), name)
            self._check_cells(name, html)

    def test_integer_values_get_commas_on_screen_and_in_pdf(self):
        html = self.client.get(self.screens()["deposits"]).content.decode()
        self.assertIn("1,500,000", numeric_cells(html))
        html = self.client.get(self.screens()["sales_invoice"], follow=True).content.decode()
        self.assertIn("1,234,572", numeric_cells(html))     # new meter, whole number
        resp, pdf_html = render_pdf_with_html(self.client, self.prints()["sales_invoice"])
        self.assertIn("1,234,572", numeric_cells(pdf_html))
        self.assertIn("1,234,572", pdf_text(resp.content))

    def test_decimal_values_group_only_the_integer_part(self):
        html = self.client.get(self.screens()["nozzle_ledger"]).content.decode()
        cells = numeric_cells(html)
        self.assertIn("1,234.75", cells)
        self.assertIn("100.5", cells)
        self.assertIn("0.25", cells)
        resp, pdf_html = render_pdf_with_html(self.client, self.prints()["nozzle_ledger"])
        self.assertIn("1,234.75", numeric_cells(pdf_html))
        self.assertIn("1,234.75", pdf_text(resp.content))
        # A grouped decimal with a fractional tail, from a different section.
        html = self.client.get(self.screens()["purchases_list"]).content.decode()
        self.assertIn("1,200.5", numeric_cells(html))
        self.assertIn("2,000", numeric_cells(html))

    def test_identifiers_and_dates_are_never_grouped(self):
        html = self.client.get(self.screens()["purchases_list"]).content.decode()
        self.assertIn("9001234", html)
        self.assertNotIn("9,001,234", html)
        self.assertIn("55Ab123", html)
        seals = self.client.get("/seals/?start_date=2026-08-01&end_date=2026-08-01").content.decode()
        self.assertIn("1234567", seals)
        self.assertNotIn("1,234,567</td>", seals)
        stmt = self.client.get(self.screens()["statement"]).content.decode()
        self.assertIn('value="1405"', stmt)
        self.assertNotIn("1,405", stmt)
        dep = self.client.get(self.screens()["deposit_decade"]).content.decode()
        self.assertIn("D-100200", dep)
        self.assertIn("1405/05/10", dep)

    def test_stored_values_are_unchanged(self):
        self.assertEqual(NozzleSale.objects.get(nozzle=self.n2).new_meter, Decimal("1234.75"))
        self.assertEqual(Deposit.objects.get().deposit_amount, Decimal("1500000.00"))
        self.assertEqual(PurchaseInvoice.objects.filter(tank=self.stank).get().quantity, 2000)
