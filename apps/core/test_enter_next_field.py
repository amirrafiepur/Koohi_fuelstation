"""
Enter-to-next-field in every data-entry form (templates/partials/_enter_next_field.html,
included once by base.html; forms opt in with data-enter-next).

Per section: the real rendered form page is driven in jsdom by
js_tests/enter_next_field.js (skipped when Node or the `jsdom` package is not
installed -- see apps/reports/test_nozzle_ledger_keyboard.py), plus structural
checks that always run.
"""

import datetime
import json
import re
import subprocess
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.deposits.models import Deposit
from apps.license.models import License
from apps.reports.test_nozzle_ledger_keyboard import NODE, NODE_ENV
from apps.stations.models import Nozzle, Product, Station, Tank

User = get_user_model()
HARNESS = Path(__file__).parent / "js_tests" / "enter_next_field.js"


def marked_forms(html):
    """<form> tags carrying the opt-in attribute (the shared script's own
    selector text also contains the word, so look at real tags only)."""
    return re.findall(r"<form[^>]*\bdata-enter-next\b[^>]*>", html)


class EnterNextBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op_enter", password="testpass123")
        License.objects.create(start_date=datetime.date.today() - datetime.timedelta(days=3), duration_days=365)
        station = Station.objects.create(name="S", province="P", city="C")
        self.regular = Tank.objects.create(station=station, product=Product.objects.create(name="Regular"), capacity=50000)
        self.super = Tank.objects.create(station=station, product=Product.objects.create(name="Super"), capacity=30000)
        self.nozzle = Nozzle.objects.create(tank=self.regular, number=1)
        self.client.login(username="op_enter", password="testpass123")

    def get(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, url)
        return resp.content.decode()

    def run_harness(self, html, spec):
        self.assertIsNotNone(NODE)
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text(html, encoding="utf-8")
            spec_file = Path(tmp) / "spec.json"
            spec_file.write_text(json.dumps({"file": str(page), **spec}), encoding="utf-8")
            result = subprocess.run([NODE, str(HARNESS), str(spec_file)], env=NODE_ENV,
                                    capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        checks = json.loads(result.stdout)
        self.assertGreaterEqual(len(checks), 18)
        failed = [name for name, ok in checks.items() if not ok]
        self.assertEqual(failed, [], f"failed Enter-to-next-field checks: {failed}")


# ---------------------------------------------------------------- واریزی‌ها

DEPOSIT_SPEC = {
    "fields": ["date", "year", "month", "decade", "deposit_amount", "difference_amount", "document_number"],
    "required": ["date", "year", "month", "decade", "deposit_amount", "difference_amount"],
    "optional": ["document_number"],
    "fill": {"date": "1405/05/10", "year": "1405", "month": "5", "deposit_amount": "1500000",
             "difference_amount": "0", "document_number": "A-1"},
}


class DepositsEnterNextTests(EnterNextBase):
    def test_new_and_edit_forms_are_marked_and_tables_are_not(self):
        new = self.get("/deposits/new/")
        self.assertEqual(len(marked_forms(new)), 1)
        deposit = Deposit.objects.create(date=datetime.date.today(), year=1405, month=5, decade="first",
                                         deposit_amount=Decimal("100"))
        edit = self.get(f"/deposits/{deposit.pk}/edit/")
        self.assertEqual(len(marked_forms(edit)), 1)
        for url in ("/deposits/?year=1405&month=5", "/deposits/1405/5/first/"):
            self.assertEqual(marked_forms(self.get(url)), [], url)

    def test_the_shared_script_is_on_the_page_exactly_once(self):
        self.assertEqual(self.get("/deposits/new/").count("var NOT_FIELDS"), 1)

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_new_deposit_form_behaviour(self):
        self.run_harness(self.get("/deposits/new/"), DEPOSIT_SPEC)

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_edit_deposit_form_behaviour(self):
        deposit = Deposit.objects.create(date=datetime.date.today(), year=1405, month=5, decade="first",
                                         deposit_amount=Decimal("100"), document_number="X")
        self.run_harness(self.get(f"/deposits/{deposit.pk}/edit/"), DEPOSIT_SPEC)


# ---------------------------------------------------------------- فاکتورهای خرید

class PurchasesEnterNextTests(EnterNextBase):
    SPEC = {
        "fields": ["program_number", "tanker_number", "quantity", "purchase_rate"],
        "required": ["quantity", "purchase_rate"],
        "optional": ["program_number", "tanker_number"],
        "fill": {"program_number": "9001", "tanker_number": "55Ab123", "quantity": "12000", "purchase_rate": "1200.5"},
    }

    def new_url(self):
        return f"/purchases/{datetime.date.today().isoformat()}/tank/{self.regular.id}/new/"

    def test_form_is_marked_and_the_old_inline_script_is_gone(self):
        html = self.get(self.new_url())
        self.assertEqual(len(marked_forms(html)), 1)
        self.assertNotIn("fields[index + 1].focus()", html)       # replaced by the shared script
        self.assertEqual(html.count("var NOT_FIELDS"), 1)
        self.assertEqual(marked_forms(self.get("/purchases/")), [])

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_new_purchase_form_behaviour(self):
        self.run_harness(self.get(self.new_url()), self.SPEC)

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_edit_purchase_form_behaviour(self):
        from apps.purchases.models import PurchaseInvoice
        from apps.workday.models import DailyWorkingDay
        wd = DailyWorkingDay.objects.create(date=datetime.date.today())
        inv = PurchaseInvoice.objects.create(working_day=wd, tank=self.regular, quantity=1000,
                                             purchase_rate=Decimal("1200"), program_number="1", tanker_number="T1")
        url = f"/purchases/{wd.date.isoformat()}/invoice/{inv.pk}/edit/"
        self.run_harness(self.get(url), self.SPEC)


# ---------------------------------------------------------------- فاکتورهای فروش

class SalesEnterNextTests(EnterNextBase):
    SPEC = {
        "fields": ["previous_meter", "new_meter", "test", "sales_rate"],
        "required": ["previous_meter", "new_meter", "test", "sales_rate"],
        "optional": [],
        "fill": {"previous_meter": "1334572", "new_meter": "1335000.5", "test": "5", "sales_rate": "1200"},
        "f2": True,
    }

    def setUp(self):
        super().setUp()
        License.objects.all().delete()
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)

    URL = "/sales/invoices/2026-08-01/nozzle/1/"

    def test_form_is_marked_with_f2_and_content_intact(self):
        html = self.get(self.URL)
        self.assertEqual(len(marked_forms(html)), 1)
        self.assertIn("e.key === 'F2'", html)                 # existing F2 shortcut untouched
        self.assertIn("requestSubmit()", html)
        self.assertEqual(marked_forms(self.get("/sales/invoices/")), [])

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_new_entry_form_behaviour(self):
        self.run_harness(self.get(self.URL), self.SPEC)

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_prefilled_previous_meter_form_behaviour(self):
        """With the previous meter auto-filled (and trimmed), Enter still walks the form
        and the pre-filled value is selected so it can be typed over."""
        from apps.sales.models import NozzleSale, SalesInvoice
        from apps.workday.models import DailyWorkingDay
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 31))
        inv = SalesInvoice.objects.create(working_day=wd, operator=self.user)
        NozzleSale.objects.create(sales_invoice=inv, nozzle=self.nozzle, previous_meter=Decimal("0"),
                                  new_meter=Decimal("1334572"), test=Decimal("0"), sales_rate=Decimal("1200"))
        self.run_harness(self.get(self.URL), self.SPEC)

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_negative_meter_warning_form_behaviour(self):
        resp = self.client.post(self.URL, {"previous_meter": "1000", "new_meter": "900", "test": "0", "sales_rate": "1200"})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("confirm_negative_meter", html)
        self.run_harness(html, {**self.SPEC, "fill": {"previous_meter": "1000", "new_meter": "900", "test": "0", "sales_rate": "1200"}})


# ---------------------------------------------------------------- پلمپ‌ها

class SealsEnterNextTests(EnterNextBase):
    SPEC = {
        "fields": ["nozzle", "section", "date", "seal_number"],
        "required": ["nozzle", "section", "date", "seal_number"],
        "optional": [],
        "fill": {"date": "1405/05/10", "seal_number": "778899"},
    }

    def test_forms_are_marked_and_list_is_not(self):
        self.assertEqual(len(marked_forms(self.get("/seals/new/"))), 1)
        self.assertEqual(marked_forms(self.get("/seals/")), [])

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_new_seal_form_behaviour(self):
        self.run_harness(self.get("/seals/new/"), self.SPEC)

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_edit_seal_form_behaviour(self):
        from apps.seals.models import NozzleSeal
        seal = NozzleSeal.objects.create(nozzle=self.nozzle, section="flag_door_1",
                                         date=datetime.date.today(), seal_number="1")
        self.run_harness(self.get(f"/seals/{seal.pk}/edit/"), self.SPEC)


# ---------------------------------------------------------------- موجودی مخازن

class InventoryEnterNextTests(EnterNextBase):
    def setUp(self):
        super().setUp()
        License.objects.all().delete()
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)

    def test_forms_are_marked_and_the_day_page_is_not(self):
        self.assertEqual(len(marked_forms(self.get(f"/inventory/2026-07-23/tank/{self.regular.id}/actual/"))), 1)
        self.assertEqual(len(marked_forms(self.get(f"/inventory/2026-07-23/tank/{self.regular.id}/opening/"))), 1)
        self.assertEqual(marked_forms(self.get("/inventory/2026-07-23/")), [])

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_actual_inventory_form_behaviour(self):
        self.run_harness(self.get(f"/inventory/2026-07-23/tank/{self.regular.id}/actual/"), {
            "fields": ["actual_inventory"], "required": ["actual_inventory"], "optional": [],
            "fill": {"actual_inventory": "90000.75"}})

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_opening_inventory_form_behaviour(self):
        self.run_harness(self.get(f"/inventory/2026-07-23/tank/{self.regular.id}/opening/"), {
            "fields": ["opening_quantity"], "required": ["opening_quantity"], "optional": [],
            "fill": {"opening_quantity": "100000"}})


# ---------------------------------------------------------------- مقایسه سیستم مکانیکی و دیجیتال

class ComparisonEnterNextTests(EnterNextBase):
    FIELDS = ["beginning_inventory", "received_quantity", "test_return", "overage",
              "sales_quantity", "shortage", "ending_inventory"]

    def entry_url(self):
        from apps.comparison.models import DigitalEntry
        self.get("/comparison/?year=1405&month=5")            # creates the month's entries
        return f"/comparison/entry/{DigitalEntry.objects.first().id}/edit/"

    def test_form_is_marked_and_the_report_is_not(self):
        self.assertEqual(len(marked_forms(self.get(self.entry_url()))), 1)
        self.assertEqual(marked_forms(self.get("/comparison/?year=1405&month=5")), [])

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_digital_entry_form_behaviour(self):
        self.run_harness(self.get(self.entry_url()), {
            "fields": self.FIELDS, "required": self.FIELDS, "optional": [],
            "fill": {f: str(10 + i) for i, f in enumerate(self.FIELDS)}})


# ---------------------------------------------------------------- صورت وضعیت ماهانه

class StatementEnterNextTests(EnterNextBase):
    def entry_id(self):
        from apps.statement.models import StatementEntry
        self.get("/statement/?year=1405&month=5")
        return StatementEntry.objects.first().id

    def test_digital_sales_form_is_marked_and_the_statement_table_forms_are_not(self):
        entry = self.entry_id()
        self.assertEqual(len(marked_forms(self.get(f"/statement/entry/{entry}/digital-sales/"))), 1)
        # The per-row tanker-capacity box lives inside the table: left exactly as it was.
        self.assertEqual(marked_forms(self.get("/statement/?year=1405&month=5")), [])

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_digital_sales_form_behaviour(self):
        entry = self.entry_id()
        self.run_harness(self.get(f"/statement/entry/{entry}/digital-sales/"), {
            "fields": ["digital_sales"], "required": [], "optional": ["digital_sales"],
            "fill": {"digital_sales": "12345.5"}})


# ---------------------------------------------------------------- لایسنس و حساب کاربری

class LicenseEnterNextTests(EnterNextBase):
    def test_renewal_form_is_marked(self):
        self.assertEqual(len(marked_forms(self.get("/license/renew/"))), 1)

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_renewal_form_behaviour(self):
        self.run_harness(self.get("/license/renew/"), {
            "fields": ["password"], "required": ["password"], "optional": [], "fill": {"password": "secret"}})


class AccountsEnterNextTests(EnterNextBase):
    """Login, first-run setup and password recovery. Several of these pages are only reachable
    in special states, so they are rendered from their real templates and forms."""

    def render(self, template, form):
        from django.template.loader import render_to_string
        return render_to_string(template, {"form": form})

    def test_all_account_forms_are_marked(self):
        from apps.accounts.forms import (FirstOperatorSetupForm, OperatorLoginForm,
                                         OperatorSetPasswordForm, SecurityAnswerForm)
        client = self.client_class()
        self.assertEqual(len(marked_forms(client.get("/accounts/login/").content.decode())), 1)
        for template, form in (("accounts/first_setup.html", FirstOperatorSetupForm()),
                               ("accounts/forgot_password.html", SecurityAnswerForm()),
                               ("accounts/reset_password.html", OperatorSetPasswordForm(self.user))):
            self.assertEqual(len(marked_forms(self.render(template, form))), 1, template)

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_login_form_behaviour(self):
        html = self.client_class().get("/accounts/login/").content.decode()
        self.run_harness(html, {"fields": ["username", "password"], "required": ["username", "password"],
                                "optional": [], "fill": {"username": "operator1", "password": "secret"}})

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_first_setup_form_behaviour(self):
        from apps.accounts.forms import FirstOperatorSetupForm
        fields = ["setup_password", "username", "password1", "password2", "security_question", "security_answer"]
        self.run_harness(self.render("accounts/first_setup.html", FirstOperatorSetupForm()), {
            "fields": fields, "required": fields, "optional": [],
            "fill": {"setup_password": "setup", "username": "operator1", "password1": "Secret-pass-123",
                     "password2": "Secret-pass-123", "security_question": "q?", "security_answer": "a"}})

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_forgot_password_form_behaviour(self):
        from apps.accounts.forms import SecurityAnswerForm
        self.run_harness(self.render("accounts/forgot_password.html", SecurityAnswerForm()), {
            "fields": ["answer"], "required": ["answer"], "optional": [], "fill": {"answer": "x"}})

    @unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
    def test_reset_password_form_behaviour(self):
        from apps.accounts.forms import OperatorSetPasswordForm
        self.run_harness(self.render("accounts/reset_password.html", OperatorSetPasswordForm(self.user)), {
            "fields": ["new_password1", "new_password2"], "required": ["new_password1", "new_password2"],
            "optional": [], "fill": {"new_password1": "Secret-pass-123", "new_password2": "Secret-pass-123"}})

    def test_login_still_works_with_the_enter_script_present(self):
        client = self.client_class()
        resp = client.post("/accounts/login/", {"username": "op_enter", "password": "testpass123"})
        self.assertEqual(resp.status_code, 302)
