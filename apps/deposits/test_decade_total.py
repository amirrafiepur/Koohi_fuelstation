"""
"مجموع واریزی دهه" on a decade's deposits page and in its PDF.

Hand-worked fixture (JALALI 1405/05):
  first decade : 1,500,000 + 250,000.50 + 99,999        = 1,849,999.5
  second decade: 700,000 + 300,000                      = 1,000,000
  third decade : (none)                                 = 0
  1405/06 first decade (another month, must never leak) = 5,000,000
"""

import datetime
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.test_number_display import pdf_text, render_pdf_with_html
from apps.deposits import services as deposit_services
from apps.deposits.models import Deposit
from apps.license.models import License

User = get_user_model()


def screen_total(html):
    m = re.search(r'data-total="decade"[^>]*>([^<]*)<', html)
    return m.group(1).strip() if m else None


def pdf_total(html):
    block = html.split("print-summary", 1)[1].split("</table>", 1)[0]
    return re.search(r'class="numeric"[^>]*>([^<]*)<', block).group(1).strip()


class DecadeTotalTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        self.client.login(username="op1", password="testpass123")
        make = lambda **kw: Deposit.objects.create(year=1405, month=kw.pop("month", 5), **kw)
        self.d1 = make(date=datetime.date(2026, 7, 24), decade="first", deposit_amount=Decimal("1500000"), document_number="A-1")
        self.d2 = make(date=datetime.date(2026, 7, 26), decade="first", deposit_amount=Decimal("250000.50"), document_number="A-2")
        self.d3 = make(date=datetime.date(2026, 7, 30), decade="first", deposit_amount=Decimal("99999"),
                       difference_amount=Decimal("12"), document_number="A-3")
        make(date=datetime.date(2026, 8, 3), decade="second", deposit_amount=Decimal("700000"))
        make(date=datetime.date(2026, 8, 5), decade="second", deposit_amount=Decimal("300000"))
        make(date=datetime.date(2026, 8, 25), month=6, decade="first", deposit_amount=Decimal("5000000"))

    def url(self, month, decade, year=1405):
        return f"/deposits/{year}/{month}/{decade}/"

    def print_url(self, month, decade, year=1405):
        return f"/print/deposits-decade/?year={year}&month={month}&decade={decade}"

    # --- service ---------------------------------------------------------

    def test_service_equals_the_sum_of_the_decades_records(self):
        for month, decade, expected in ((5, "first", "1849999.5"), (5, "second", "1000000"),
                                        (5, "third", "0"), (6, "first", "5000000")):
            records = deposit_services.deposits_in_decade(1405, month, decade)
            self.assertEqual(deposit_services.decade_total(1405, month, decade),
                             sum((d.deposit_amount for d in records), Decimal("0")))
            self.assertEqual(deposit_services.decade_total(1405, month, decade), Decimal(expected))

    def test_agrees_with_the_existing_decade_totals_on_the_list_page(self):
        rows = {r["decade"]: r["total"] for r in deposit_services.decade_totals(1405, 5)}
        for decade, total in rows.items():
            self.assertEqual(deposit_services.decade_total(1405, 5, decade), total)

    # --- screen ----------------------------------------------------------

    def test_screen_shows_the_decade_total_above_the_table(self):
        html = self.client.get(self.url(5, "first")).content.decode()
        self.assertIn("مجموع واریزی دهه", html)
        self.assertEqual(screen_total(html), "1,849,999.5")
        self.assertLess(html.index('id="decade-total"'), html.index("<table"))

    def test_total_equals_the_sum_of_the_amounts_shown_in_the_table(self):
        html = self.client.get(self.url(5, "first")).content.decode()
        body = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        cells = re.findall(r'<td style="padding: 0.4rem;" class="numeric">([^<]*)</td>', body)
        amounts = [Decimal(c.replace(",", "")) for i, c in enumerate(cells) if i % 3 == 1]  # date, amount, difference
        self.assertEqual(len(amounts), 3)
        self.assertEqual(sum(amounts), Decimal("1849999.5"))
        self.assertEqual(screen_total(html), "1,849,999.5")

    def test_each_decade_and_month_gets_its_own_total(self):
        self.assertEqual(screen_total(self.client.get(self.url(5, "second")).content.decode()), "1,000,000")
        self.assertEqual(screen_total(self.client.get(self.url(5, "third")).content.decode()), "0")
        self.assertEqual(screen_total(self.client.get(self.url(6, "first")).content.decode()), "5,000,000")
        self.assertEqual(screen_total(self.client.get(self.url(7, "first")).content.decode()), "0")

    def test_total_follows_changed_records(self):
        self.client.post(reverse("deposits:deposit_delete", args=[self.d2.pk]))
        self.assertEqual(screen_total(self.client.get(self.url(5, "first")).content.decode()), "1,599,999")
        self.d1.deposit_amount = Decimal("2000000")
        self.d1.save()
        self.assertEqual(screen_total(self.client.get(self.url(5, "first")).content.decode()), "2,099,999")
        Deposit.objects.create(year=1405, month=5, decade="first", date=datetime.date(2026, 7, 25),
                               deposit_amount=Decimal("1"))
        self.assertEqual(screen_total(self.client.get(self.url(5, "first")).content.decode()), "2,100,000")

    def test_empty_decade_shows_zero_and_the_empty_message(self):
        html = self.client.get(self.url(5, "third")).content.decode()
        self.assertEqual(screen_total(html), "0")
        self.assertIn("در این دهه واریزی ثبت نشده است", html)

    # --- PDF -------------------------------------------------------------

    def test_pdf_total_matches_the_screen_for_every_decade(self):
        for month, decade in ((5, "first"), (5, "second"), (5, "third"), (6, "first")):
            screen = screen_total(self.client.get(self.url(month, decade)).content.decode())
            resp, html = render_pdf_with_html(self.client, self.print_url(month, decade))
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.content.startswith(b"%PDF"))
            self.assertEqual(pdf_total(html), screen, (month, decade))

    def test_pdf_has_the_summary_above_the_table_and_in_the_file_text(self):
        resp, html = render_pdf_with_html(self.client, self.print_url(5, "first"))
        self.assertLess(html.index("مجموع واریزی دهه"), html.index("تاریخ سند"))
        text = pdf_text(resp.content)
        for needle in ("مجموع واریزی دهه", "1,849,999.5", "1,500,000", "250,000.5", "A-1"):
            self.assertIn(needle, text)

    def test_pdf_for_an_empty_decade_still_renders_with_zero_total(self):
        resp, html = render_pdf_with_html(self.client, self.print_url(5, "third"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(pdf_total(html), "0")
        self.assertIn("واریزی ثبت نشده است", html)

    # --- nothing stored changes -------------------------------------------

    def test_viewing_changes_no_stored_data(self):
        before = list(Deposit.objects.values_list("id", "deposit_amount", "difference_amount", "decade").order_by("id"))
        self.client.get(self.url(5, "first"))
        self.client.get(self.print_url(5, "first"))
        self.assertEqual(before, list(
            Deposit.objects.values_list("id", "deposit_amount", "difference_amount", "decade").order_by("id")))
