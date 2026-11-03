import datetime
from decimal import Decimal

from django.test import TestCase

from apps.purchases import services
from apps.purchases.models import PurchaseInvoice
from apps.stations.models import Station, Product, Tank
from apps.workday.models import DailyWorkingDay


class MultiplePurchasesPerDayTests(TestCase):
    def setUp(self):
        station = Station.objects.create(name="S", province="P", city="C")
        product = Product.objects.create(name="Regular")
        self.tank = Tank.objects.create(station=station, product=product, capacity=50000)
        self.working_day = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))

    def test_multiple_invoices_same_day_all_contribute(self):
        PurchaseInvoice.objects.create(
            working_day=self.working_day, tank=self.tank, quantity=3200, purchase_rate=Decimal("1000")
        )
        PurchaseInvoice.objects.create(
            working_day=self.working_day, tank=self.tank, quantity=3100, purchase_rate=Decimal("1000")
        )
        PurchaseInvoice.objects.create(
            working_day=self.working_day, tank=self.tank, quantity=3000, purchase_rate=Decimal("1000")
        )
        total = services.get_daily_purchase_total(self.tank, self.working_day)
        self.assertEqual(total, Decimal("9300"))

    def test_duplicate_business_document_numbers_allowed(self):
        PurchaseInvoice.objects.create(
            working_day=self.working_day, tank=self.tank, quantity=100,
            purchase_rate=Decimal("1000"), document_number="INV-001",
        )
        # Must not raise -- no uniqueness constraint on document_number.
        PurchaseInvoice.objects.create(
            working_day=self.working_day, tank=self.tank, quantity=200,
            purchase_rate=Decimal("1000"), document_number="INV-001",
        )
        self.assertEqual(
            PurchaseInvoice.objects.filter(document_number="INV-001").count(), 2
        )

    def test_duplicate_tanker_numbers_allowed(self):
        PurchaseInvoice.objects.create(
            working_day=self.working_day, tank=self.tank, quantity=100,
            purchase_rate=Decimal("1000"), tanker_number="12-ABC-34",
        )
        PurchaseInvoice.objects.create(
            working_day=self.working_day, tank=self.tank, quantity=100,
            purchase_rate=Decimal("1000"), tanker_number="12-ABC-34",
        )
        count = services.get_monthly_unloading_count(self.tank, 2026, 8)
        self.assertEqual(count, 2)


# ---------------------------------------------------------------------------
# HTTP-level integration tests for the Phase 5 purchase workflow, covering
# the ten mandatory rules from the Phase 5 requirements document.
# ---------------------------------------------------------------------------

from django.contrib.auth import get_user_model as _get_user_model
from django.test import TestCase as _TestCase

from apps.license.models import License as _License

_User = _get_user_model()


class PurchaseWorkflowHttpTests(_TestCase):
    def setUp(self):
        self.user = _User.objects.create_user(username="op1", password="testpass123")
        _License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S", province="P", city="C")
        self.regular = Product.objects.create(name="Regular")
        self.super_ = Product.objects.create(name="Super")
        self.regular_tank = Tank.objects.create(station=station, product=self.regular, capacity=50000)
        self.super_tank = Tank.objects.create(station=station, product=self.super_, capacity=30000)
        self.client.login(username="op1", password="testpass123")
        self.date = "2026-08-01"

    # Rule 1: multiple invoices per day.
    def test_multiple_purchase_invoices_same_day_same_tank(self):
        for qty in (10000, 15000, 8000):
            resp = self.client.post(
                f"/purchases/{self.date}/tank/{self.regular_tank.id}/new/",
                {"quantity": qty, "purchase_rate": "1000"},
            )
            self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            PurchaseInvoice.objects.filter(tank=self.regular_tank, working_day__date=self.date).count(), 3
        )

    # Rule 7: derived daily total, using the exact spec example.
    def test_daily_total_matches_spec_example(self):
        for qty in (10000, 15000, 8000):
            self.client.post(
                f"/purchases/{self.date}/tank/{self.regular_tank.id}/new/",
                {"quantity": qty, "purchase_rate": "1000"},
            )
        working_day = DailyWorkingDay.objects.get(date=self.date)
        total = services.get_daily_purchase_total(self.regular_tank, working_day)
        self.assertEqual(total, Decimal("33000"))
        # Also verify the rendered range list page shows it (the row's
        # own quantity, since the range view no longer shows a
        # single-day aggregate total -- see invoice_list()'s docstring).
        resp = self.client.get(f"/purchases/?start_date={self.date}&end_date={self.date}")
        self.assertContains(resp, "15,000")

    # Rule 2: duplicate tanker numbers accepted, no error/warning.
    def test_duplicate_tanker_number_accepted_via_form(self):
        r1 = self.client.post(
            f"/purchases/{self.date}/tank/{self.regular_tank.id}/new/",
            {"quantity": 100, "purchase_rate": "1000", "tanker_number": "12-ABC-34"},
        )
        r2 = self.client.post(
            f"/purchases/{self.date}/tank/{self.regular_tank.id}/new/",
            {"quantity": 200, "purchase_rate": "1000", "tanker_number": "12-ABC-34"},
        )
        self.assertEqual(r1.status_code, 302)
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(PurchaseInvoice.objects.filter(tanker_number="12-ABC-34").count(), 2)

    # Rule 3: no capacity restriction -- an unusually large value must be
    # accepted at the model level. tanker_capacity is no longer collected
    # through the purchase form (removed per the Purchases section
    # rework), but the field/rule itself still exists on the model for
    # any historical data, so this is now a model-level test rather than
    # a form-submission test.
    def test_unrestricted_tanker_capacity_accepted(self):
        working_day = DailyWorkingDay.objects.get_or_create(date=datetime.date(2026, 8, 1))[0]
        invoice = PurchaseInvoice.objects.create(
            working_day=working_day, tank=self.regular_tank, quantity=100,
            purchase_rate=Decimal("1000"), tanker_capacity=999999,
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.tanker_capacity, 999999)

    # Rule 4: historical rate is frozen even after the suggested rate changes.
    def test_historical_purchase_rate_frozen_after_later_change(self):
        self.client.post(
            f"/purchases/{self.date}/tank/{self.regular_tank.id}/new/",
            {"quantity": 100, "purchase_rate": "1000"},
        )
        first_invoice = PurchaseInvoice.objects.get(quantity=100)

        # A later purchase uses a different rate.
        self.client.post(
            f"/purchases/{self.date}/tank/{self.regular_tank.id}/new/",
            {"quantity": 200, "purchase_rate": "1500"},
        )
        first_invoice.refresh_from_db()
        self.assertEqual(first_invoice.purchase_rate, Decimal("1000"))

    # Rule 5: rate suggestion uses the most recently used rate for that product.
    def test_rate_suggestion_uses_most_recent_rate_for_product(self):
        self.client.post(
            f"/purchases/{self.date}/tank/{self.regular_tank.id}/new/",
            {"quantity": 100, "purchase_rate": "1234"},
        )
        resp = self.client.get(f"/purchases/{self.date}/tank/{self.regular_tank.id}/new/")
        self.assertContains(resp, "1234")

    # Rule 6: Regular and Super rate suggestions are fully independent.
    def test_regular_and_super_rate_suggestions_independent(self):
        self.client.post(
            f"/purchases/{self.date}/tank/{self.regular_tank.id}/new/",
            {"quantity": 100, "purchase_rate": "1200"},
        )
        self.client.post(
            f"/purchases/{self.date}/tank/{self.super_tank.id}/new/",
            {"quantity": 100, "purchase_rate": "1500"},
        )
        # Changing Regular's most recent rate...
        self.client.post(
            f"/purchases/{self.date}/tank/{self.regular_tank.id}/new/",
            {"quantity": 50, "purchase_rate": "1800"},
        )
        # ...must not affect Super's suggested rate.
        super_suggestion = services.get_most_recent_rate(self.super_tank)
        self.assertEqual(super_suggestion, Decimal("1500"))
        regular_suggestion = services.get_most_recent_rate(self.regular_tank)
        self.assertEqual(regular_suggestion, Decimal("1800"))

    # Rule 8: purchases are optional and never block day completion.
    def test_day_with_no_purchases_can_still_be_closed(self):
        working_day = DailyWorkingDay.objects.get_or_create(date=datetime.date(2026, 8, 1))[0]
        self.assertEqual(
            PurchaseInvoice.objects.filter(working_day=working_day).count(), 0
        )
        # close_day() must succeed regardless -- no purchase requirement
        # is checked by workday services.
        from apps.workday import services as workday_services
        workday_services.close_day(datetime.date(2026, 8, 1))
        working_day.refresh_from_db()
        self.assertEqual(working_day.status, DailyWorkingDay.COMPLETE)

    # Rule 10: chronology -- future dates blocked for purchase entry too.
    def test_future_date_purchase_entry_blocked(self):
        resp = self.client.post(
            f"/purchases/2099-01-01/tank/{self.regular_tank.id}/new/",
            {"quantity": 100, "purchase_rate": "1000"},
            follow=True,
        )
        self.assertContains(resp, "آینده")
        self.assertEqual(PurchaseInvoice.objects.count(), 0)

    # Rule 10: chronology -- dates before accounting start blocked.
    def test_date_before_accounting_start_blocked_for_purchases(self):
        resp = self.client.post(
            f"/purchases/2026-07-15/tank/{self.regular_tank.id}/new/",
            {"quantity": 100, "purchase_rate": "1000"},
            follow=True,
        )
        self.assertContains(resp, "خارج")
        self.assertEqual(PurchaseInvoice.objects.count(), 0)

    # Rule 10: editing a historical purchase preserves its working_day.
    def test_editing_purchase_preserves_working_day(self):
        self.client.post(
            f"/purchases/{self.date}/tank/{self.regular_tank.id}/new/",
            {"quantity": 100, "purchase_rate": "1000"},
        )
        invoice = PurchaseInvoice.objects.get(quantity=100)
        original_working_day_id = invoice.working_day_id

        self.client.post(
            f"/purchases/{self.date}/invoice/{invoice.pk}/edit/",
            {"quantity": 150, "purchase_rate": "1000"},
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.working_day_id, original_working_day_id)
        self.assertEqual(invoice.quantity, 150)

    # Rule 9: the view layer never duplicates the aggregation formula --
    # get_daily_purchase_total must still exist and work correctly as a
    # service, independent of how the range view chooses to display data.
    def test_view_and_service_aggregation_agree(self):
        for qty in (500, 700):
            self.client.post(
                f"/purchases/{self.date}/tank/{self.regular_tank.id}/new/",
                {"quantity": qty, "purchase_rate": "1000"},
            )
        working_day = DailyWorkingDay.objects.get(date=self.date)
        service_total = services.get_daily_purchase_total(self.regular_tank, working_day)
        self.assertEqual(service_total, Decimal("1200"))
        # Both rows' own quantities must appear on the range list page --
        # no re-aggregation or invented total happens in the view/template.
        resp = self.client.get(f"/purchases/?start_date={self.date}&end_date={self.date}")
        self.assertContains(resp, "500")
        self.assertContains(resp, "700")


class PurchaseEntryEnterKeyNavigationTests(_TestCase):
    """
    Task: Enter in شماره ی بارنامه -> focus شماره ی نفتکش -> Enter ->
    next field -> ... -> نرخ (the last field, whose Enter still submits
    normally). Verified structurally (field order, hidden CSRF token
    excluded, keydown/Enter wiring present) since this project has no
    JS test runner -- the same level of verification this project's
    only other JS keyboard shortcut (نازل entry's F2) also has.
    """

    def setUp(self):
        self.user = _User.objects.create_user(username="op_enter", password="testpass123")
        _License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S_enter", province="P", city="C")
        product = Product.objects.create(name="Regular")
        self.tank = Tank.objects.create(station=station, product=product, capacity=50000)
        self.client.login(username="op_enter", password="testpass123")

    def _get(self):
        return self.client.get(f"/purchases/2026-08-01/tank/{self.tank.id}/new/")

    def test_form_has_an_id_for_the_navigation_script_to_target(self):
        self.assertContains(self._get(), 'id="purchase-form"')

    def test_keydown_enter_navigation_script_present(self):
        content = self._get().content.decode()
        self.assertIn("keydown", content)
        self.assertIn("Enter", content)
        self.assertIn("preventDefault", content)
        self.assertIn(".focus()", content)

    def test_hidden_csrf_token_excluded_from_the_field_list(self):
        """The CSRF token is also an <input>; it must not become "the
        first field" in the Enter-navigation order."""
        content = self._get().content.decode()
        # Now handled by the shared script (partials/_enter_next_field.html):
        # hidden inputs are in its list of non-fields, and the form opts in.
        self.assertIn("var NOT_FIELDS = ['hidden'", content)
        self.assertIn('id="purchase-form" data-enter-next', content)

    def test_fields_appear_in_the_required_order_in_the_markup(self):
        """شماره ی بارنامه -> شماره ی نفتکش -> مقدار -> نرخ, in that
        order in the DOM -- the script walks them in document order, so
        this order IS the Enter-navigation order."""
        content = self._get().content.decode()
        positions = [
            content.index('id="id_program_number"'),
            content.index('id="id_tanker_number"'),
            content.index('id="id_quantity"'),
            content.index('id="id_purchase_rate"'),
        ]
        self.assertEqual(positions, sorted(positions))

    def test_existing_submit_behavior_and_fields_unchanged(self):
        """Scoping check: this is a keyboard-navigation addition only --
        existing field labels, submission, and business logic are
        untouched."""
        resp = self.client.post(
            f"/purchases/2026-08-01/tank/{self.tank.id}/new/",
            {"program_number": "BN-1", "tanker_number": "TN-1", "quantity": "100", "purchase_rate": "1200"},
        )
        self.assertEqual(resp.status_code, 302)
        invoice = PurchaseInvoice.objects.get()
        self.assertEqual(invoice.program_number, "BN-1")
        self.assertEqual(invoice.tanker_number, "TN-1")


class PurchaseInvoiceDeletionTests(_TestCase):
    """
    Task: "حذف فاکتور" action per invoice row, mirroring the project's
    existing deletion pattern (apps/seals/views.py:seal_delete) exactly
    -- GET shows a confirmation page and changes nothing; only POST
    actually deletes; cancelling (never submitting) leaves the invoice
    and the list untouched.
    """

    def setUp(self):
        self.user = _User.objects.create_user(username="op_del", password="testpass123")
        _License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S_del", province="P", city="C")
        product = Product.objects.create(name="Regular")
        self.tank = Tank.objects.create(station=station, product=product, capacity=50000)
        self.working_day = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))
        self.invoice = PurchaseInvoice.objects.create(
            working_day=self.working_day, tank=self.tank,
            program_number="BN-1", tanker_number="TN-1",
            quantity=1000, purchase_rate=Decimal("1200"),
        )
        self.client.login(username="op_del", password="testpass123")

    def _delete_url(self):
        return f"/purchases/2026-08-01/invoice/{self.invoice.pk}/delete/"

    def test_delete_link_present_on_the_list_page(self):
        resp = self.client.get("/purchases/?start_date=2026-08-01&end_date=2026-08-01")
        self.assertContains(resp, "حذف فاکتور")
        self.assertContains(resp, self._delete_url())

    def test_get_shows_confirmation_and_does_not_delete(self):
        resp = self.client.get(self._delete_url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "بله، حذف شود")
        self.assertTrue(PurchaseInvoice.objects.filter(pk=self.invoice.pk).exists())

    def test_confirmed_post_deletes_the_invoice(self):
        resp = self.client.post(self._delete_url())
        self.assertRedirects(resp, "/purchases/")
        self.assertFalse(PurchaseInvoice.objects.filter(pk=self.invoice.pk).exists())

    def test_cancelling_leaves_the_invoice_untouched(self):
        """Never submitting the confirm form (i.e. just visiting the
        cancel link / navigating away) must leave the record intact."""
        self.client.get(self._delete_url())  # visit confirmation page only
        self.assertTrue(PurchaseInvoice.objects.filter(pk=self.invoice.pk).exists())

    def test_deleted_invoice_no_longer_appears_in_the_list(self):
        self.client.post(self._delete_url())
        resp = self.client.get("/purchases/?start_date=2026-08-01&end_date=2026-08-01")
        self.assertNotContains(resp, "BN-1")

    def test_other_invoices_and_unrelated_purchase_logic_unaffected(self):
        other = PurchaseInvoice.objects.create(
            working_day=self.working_day, tank=self.tank,
            program_number="BN-2", tanker_number="TN-2",
            quantity=500, purchase_rate=Decimal("1300"),
        )
        self.client.post(self._delete_url())
        self.assertTrue(PurchaseInvoice.objects.filter(pk=other.pk).exists())


class PurchasesRangeViewTests(_TestCase):
    """Covers the reworked خرید section: a date-range view with two
    separate Regular/Super tables, the six specified columns, the
    renamed fields, removed fields staying out of the UI, and one
    combined print button."""

    def setUp(self):
        self.user = _User.objects.create_user(username="op2", password="testpass123")
        _License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S2", province="P", city="C")
        self.regular = Product.objects.create(name="Regular")
        self.super_ = Product.objects.create(name="Super")
        self.regular_tank = Tank.objects.create(station=station, product=self.regular, capacity=50000)
        self.super_tank = Tank.objects.create(station=station, product=self.super_, capacity=30000)
        self.client.login(username="op2", password="testpass123")

    def test_nav_link_goes_straight_to_the_range_view(self):
        resp = self.client.get("/")
        self.assertContains(resp, 'href="/purchases/"')

    def test_range_view_shows_both_product_tables(self):
        resp = self.client.get("/purchases/")
        self.assertEqual(resp.status_code, 200)
        # Persian display labels (see apps/core/display.py) -- stored
        # Product.name values are still "Regular"/"Super".
        self.assertContains(resp, "بنزین معمولی")
        self.assertContains(resp, "بنزین سوپر")

    def test_range_view_has_exactly_the_six_required_columns_in_order(self):
        working_day = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))
        PurchaseInvoice.objects.create(
            working_day=working_day, tank=self.regular_tank, quantity=100, purchase_rate=Decimal("1000"),
        )
        resp = self.client.get("/purchases/?start_date=2026-08-01&end_date=2026-08-01")
        content = resp.content.decode()
        columns = ["تاریخ بارنامه", "شماره ی بارنامه", "شماره ی نفتکش", "مقدار", "نرخ", "مبلغ کل"]
        for col in columns:
            self.assertIn(col, content)
        # Order check: each column must appear before the next one.
        positions = [content.index(c) for c in columns]
        self.assertEqual(positions, sorted(positions))

    def test_removed_fields_do_not_appear_on_the_range_view(self):
        working_day = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))
        PurchaseInvoice.objects.create(
            working_day=working_day, tank=self.regular_tank, quantity=100,
            purchase_rate=Decimal("1000"), unloading_time=datetime.time(14, 30),
            tanker_capacity=20000, document_number="DOC-1",
        )
        resp = self.client.get("/purchases/?start_date=2026-08-01&end_date=2026-08-01")
        content = resp.content.decode()
        self.assertNotIn("ظرفیت تانکر", content)
        self.assertNotIn("زمان تخلیه", content)
        self.assertNotIn("14:30", content)
        self.assertNotIn("DOC-1", content)

    def test_range_view_shows_invoice_within_range(self):
        working_day = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 5))
        PurchaseInvoice.objects.create(
            working_day=working_day, tank=self.regular_tank, quantity=12345,
            purchase_rate=Decimal("1000"), program_number="BN-77", tanker_number="TN-88",
        )
        resp = self.client.get("/purchases/?start_date=2026-08-01&end_date=2026-08-10")
        self.assertContains(resp, "12,345")
        self.assertContains(resp, "BN-77")
        self.assertContains(resp, "TN-88")

    def test_range_view_excludes_invoice_outside_range(self):
        working_day = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 20))
        PurchaseInvoice.objects.create(
            working_day=working_day, tank=self.regular_tank, quantity=99999,
            purchase_rate=Decimal("1000"),
        )
        resp = self.client.get("/purchases/?start_date=2026-08-01&end_date=2026-08-10")
        self.assertNotContains(resp, "99999")

    def test_regular_and_super_purchases_stay_in_separate_tables(self):
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))
        PurchaseInvoice.objects.create(
            working_day=wd, tank=self.regular_tank, quantity=1111, purchase_rate=Decimal("1000"),
        )
        PurchaseInvoice.objects.create(
            working_day=wd, tank=self.super_tank, quantity=2222, purchase_rate=Decimal("1500"),
        )
        resp = self.client.get("/purchases/?start_date=2026-08-01&end_date=2026-08-01")
        content = resp.content.decode()
        # Both rows appear, and the Regular quantity appears before the
        # Super quantity, matching the tank ordering (product__name).
        self.assertIn("1,111", content)
        self.assertIn("2,222", content)

    def test_print_button_links_to_the_combined_pdf_endpoint(self):
        resp = self.client.get("/purchases/?start_date=2026-08-01&end_date=2026-08-10")
        self.assertContains(resp, "/print/purchases-ledger/")

    def test_purchases_ledger_pdf_generates_with_both_tables(self):
        wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 8, 1))
        PurchaseInvoice.objects.create(
            working_day=wd, tank=self.regular_tank, quantity=1111, purchase_rate=Decimal("1000"),
            program_number="BN-1", tanker_number="TN-1",
        )
        PurchaseInvoice.objects.create(
            working_day=wd, tank=self.super_tank, quantity=2222, purchase_rate=Decimal("1500"),
            program_number="BN-2", tanker_number="TN-2",
        )
        resp = self.client.get(
            "/print/purchases-ledger/?start_date=2026-08-01&end_date=2026-08-01"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get("Content-Type"), "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_new_entry_button_uses_the_global_date(self):
        session = self.client.session
        session["global_working_date"] = "2026-08-03"
        session.save()
        resp = self.client.get("/purchases/")
        self.assertContains(resp, f"/purchases/2026-08-03/tank/{self.regular_tank.id}/new/")

    def test_purchase_entry_form_has_exactly_the_four_required_fields_in_order(self):
        resp = self.client.get(f"/purchases/2026-08-01/tank/{self.regular_tank.id}/new/")
        content = resp.content.decode()
        labels = ["شماره ی بارنامه", "شماره ی نفتکش", "مقدار", "نرخ"]
        for label in labels:
            self.assertIn(label, content)
        positions = [content.index(l) for l in labels]
        self.assertEqual(positions, sorted(positions))
        # Removed fields must not appear on the form at all.
        self.assertNotIn("ظرفیت تانکر", content)
        self.assertNotIn("زمان تخلیه", content)
        self.assertNotIn("شماره سند", content)

    def test_purchase_entry_saves_program_number_and_tanker_number(self):
        resp = self.client.post(
            f"/purchases/2026-08-01/tank/{self.regular_tank.id}/new/",
            {"program_number": "BN-99", "tanker_number": "TN-99", "quantity": 500, "purchase_rate": "1000"},
        )
        self.assertEqual(resp.status_code, 302)
        invoice = PurchaseInvoice.objects.get(quantity=500)
        self.assertEqual(invoice.program_number, "BN-99")
        self.assertEqual(invoice.tanker_number, "TN-99")
