"""
"+" keyboard shortcut on "فاکتورهای خرید" opens the new purchase invoice form.

Two layers:
  * structural checks on the rendered pages (always run);
  * real behaviour tests: the pages' actual inline scripts run in jsdom and
    are driven with KeyboardEvents by js_tests/new_invoice_shortcut.js
    (skipped when Node or the `jsdom` package is not installed; see
    apps/reports/test_nozzle_ledger_keyboard.py for how to enable them).
"""

import datetime
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.license.models import License
from apps.purchases.models import PurchaseInvoice
from apps.reports.test_nozzle_ledger_keyboard import NODE, NODE_ENV
from apps.stations.models import Product, Station, Tank

User = get_user_model()
HARNESS = Path(__file__).parent / "js_tests" / "new_invoice_shortcut.js"


class NewInvoiceShortcutBase(TestCase):
    def setUp(self):
        User.objects.create_user(username="op_plus", password="testpass123")
        License.objects.create(start_date=datetime.date.today() - datetime.timedelta(days=3), duration_days=365)
        station = Station.objects.create(name="S", province="P", city="C")
        self.regular = Tank.objects.create(station=station, product=Product.objects.create(name="Regular"), capacity=50000)
        self.super = Tank.objects.create(station=station, product=Product.objects.create(name="Super"), capacity=30000)
        self.client.login(username="op_plus", password="testpass123")

    def list_html(self):
        resp = self.client.get("/purchases/")
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()


class NewInvoiceShortcutStructureTests(NewInvoiceShortcutBase):
    def test_every_new_invoice_button_is_marked_and_the_first_has_a_tooltip(self):
        html = self.list_html()
        self.assertEqual(len(re.findall(r"<a [^>]*data-new-invoice-link", html)), 2)
        first = html.split("data-new-invoice-link", 1)[1].split(">", 1)[0]
        self.assertIn('title="میانبر صفحه‌کلید: کلید +"', first)
        second = html.split("data-new-invoice-link", 2)[2].split(">", 1)[0]
        self.assertNotIn("title=", second)

    def test_buttons_still_point_at_each_tanks_new_entry_form(self):
        html = self.list_html()
        self.assertIn(f"/tank/{self.regular.id}/new/", html)
        self.assertIn(f"/tank/{self.super.id}/new/", html)
        self.assertIn("+ فاکتور جدید", html)

    def test_the_first_link_is_the_regular_tank(self):
        """+ opens the first button's form: tanks are listed by product name, Regular first."""
        html = self.list_html()
        href = html.split('href="', 1)[1].split("data-new-invoice-link", 1)  # sanity: marker exists
        first_link = html.split("data-new-invoice-link", 1)[0].rsplit('<a href="', 1)[1].split('"', 1)[0]
        self.assertIn(f"/tank/{self.regular.id}/new/", first_link)

    def test_the_link_leads_to_a_working_form(self):
        html = self.list_html()
        href = html.split("data-new-invoice-link", 1)[0].rsplit('<a href="', 1)[1].split('"', 1)[0]
        resp = self.client.get(href)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="purchase-form"', resp.content.decode())
        self.assertIn("فاکتور خرید جدید", resp.content.decode())

    def test_script_is_only_on_the_list_page(self):
        html = self.list_html()
        self.assertIn("e.key !== '+'", html)
        href = html.split("data-new-invoice-link", 1)[0].rsplit('<a href="', 1)[1].split('"', 1)[0]
        form = self.client.get(href).content.decode()
        self.assertNotIn("data-new-invoice-link", form)
        self.assertNotIn("e.key !== '+'", form)
        self.assertNotIn("e.key !== '+'", self.client.get("/").content.decode())

    def test_existing_list_content_is_unchanged(self):
        html = self.list_html()
        for needle in ("فهرست فاکتور های خرید", "چاپ / PDF", "ثبت خرید برای روز دیگر", "از تاریخ", "تا تاریخ",
                       "JalaliCalendar.bindNavInputs"):
            self.assertIn(needle, html)

    def test_pressing_nothing_changes_stored_data(self):
        before = PurchaseInvoice.objects.count()
        self.list_html()
        self.assertEqual(PurchaseInvoice.objects.count(), before)


@unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
class NewInvoiceShortcutBehaviourTests(NewInvoiceShortcutBase):
    def test_keyboard_shortcut_behaves_as_specified(self):
        from apps.workday.models import DailyWorkingDay
        wd = DailyWorkingDay.objects.create(date=datetime.date.today())
        for tank in (self.regular, self.super):          # real rows, so table navigation has something to walk
            PurchaseInvoice.objects.create(working_day=wd, tank=tank, quantity=1000, purchase_rate=1200,
                                           program_number="1", tanker_number="T")
        list_html = self.list_html()
        self.assertIn("1,000", list_html)
        href = list_html.split("data-new-invoice-link", 1)[0].rsplit('<a href="', 1)[1].split('"', 1)[0]
        form_html = self.client.get(href).content.decode()
        other_html = self.client.get("/").content.decode()
        PurchaseInvoice.objects.all().delete()          # (invoices protect their tanks from deletion)
        Tank.objects.all().delete()
        no_tanks_html = self.list_html()

        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name, html in (("list", list_html), ("form", form_html), ("other", other_html), ("empty", no_tanks_html)):
                path = Path(tmp) / f"{name}.html"
                path.write_text(html, encoding="utf-8")
                paths.append(str(path))
            result = subprocess.run([NODE, str(HARNESS), *paths], env=NODE_ENV,
                                    capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        checks = json.loads(result.stdout)
        self.assertGreaterEqual(len(checks), 28)
        failed = [name for name, ok in checks.items() if not ok]
        self.assertEqual(failed, [], f"failed browser-behaviour checks: {failed}")
