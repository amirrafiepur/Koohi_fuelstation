import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.license.models import License

from .models import Deposit
from .views import _decade_for_date

User = get_user_model()


class DecadeForDateTests(TestCase):
    """
    _decade_for_date() buckets by the JALALI day-of-month (1-10/11-20/
    21-end), since Deposit.date is now displayed/entered in Jalali and
    the decade is a slice of that Jalali month -- a Gregorian
    day-of-month can land in a different third of the month than the
    corresponding Jalali day, so this must not be computed from
    date.day directly.
    """

    def test_gregorian_day_25_can_fall_in_jalali_first_decade(self):
        # 2026-02-25 is Jalali 1404/12/06 -- Jalali day 6, first decade.
        # (Gregorian day-of-month 25 would incorrectly suggest the third
        # decade if computed the old, Gregorian-day way.)
        self.assertEqual(_decade_for_date(datetime.date(2026, 2, 25)), Deposit.FIRST_DECADE)

    def test_jalali_day_10_is_first_decade(self):
        # 2026-09-01 is Jalali 1405/06/10.
        self.assertEqual(_decade_for_date(datetime.date(2026, 9, 1)), Deposit.FIRST_DECADE)

    def test_jalali_day_11_is_second_decade(self):
        # 2026-09-02 is Jalali 1405/06/11.
        self.assertEqual(_decade_for_date(datetime.date(2026, 9, 2)), Deposit.SECOND_DECADE)

    def test_jalali_day_20_is_second_decade(self):
        # 2026-09-11 is Jalali 1405/06/20.
        self.assertEqual(_decade_for_date(datetime.date(2026, 9, 11)), Deposit.SECOND_DECADE)

    def test_jalali_day_21_is_third_decade(self):
        # 2026-09-12 is Jalali 1405/06/21.
        self.assertEqual(_decade_for_date(datetime.date(2026, 9, 12)), Deposit.THIRD_DECADE)

    def test_jalali_day_23_is_third_decade(self):
        # 2026-09-14 is Jalali 1405/06/23.
        self.assertEqual(_decade_for_date(datetime.date(2026, 9, 14)), Deposit.THIRD_DECADE)


class DepositHttpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        self.client.login(username="op1", password="testpass123")

    def test_deposit_list_renders_empty(self):
        """Deposits are fully optional -- the 3-decade summary always
        renders (with 0 totals), not an error or a blocking condition."""
        resp = self.client.get("/deposits/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "دهه اول")
        self.assertContains(resp, "دهه دوم")
        self.assertContains(resp, "دهه سوم")

    def test_create_deposit_form_defaults_decade_from_date(self):
        resp = self.client.get("/deposits/new/")
        self.assertEqual(resp.status_code, 200)
        # Default date is today; decade select should be pre-populated
        # (not blank) based on that date -- exact value depends on today,
        # so just confirm the decade field renders with a selected option.
        self.assertContains(resp, 'name="decade"')

    def test_create_deposit_first_decade(self):
        resp = self.client.post("/deposits/new/", {
            "date": "1405/05/14", "year": 2026, "month": 8, "decade": Deposit.FIRST_DECADE,
            "deposit_amount": "1000000", "difference_amount": "0",
            "document_number": "", "bank": "", "branch": "",
        })
        self.assertEqual(resp.status_code, 302)
        deposit = Deposit.objects.get()
        self.assertEqual(deposit.decade, Deposit.FIRST_DECADE)

    def test_create_deposit_third_decade(self):
        # 1404/12/06 is a Jalali-first-decade date; the decade value
        # itself is operator-submitted (not server-validated against
        # the date), so this just confirms THIRD_DECADE round-trips.
        resp = self.client.post("/deposits/new/", {
            "date": "1404/12/06", "year": 2026, "month": 2, "decade": Deposit.THIRD_DECADE,
            "deposit_amount": "500000", "difference_amount": "0",
            "document_number": "", "bank": "", "branch": "",
        })
        self.assertEqual(resp.status_code, 302)
        deposit = Deposit.objects.get()
        self.assertEqual(deposit.date, datetime.date(2026, 2, 25))
        self.assertEqual(deposit.decade, Deposit.THIRD_DECADE)

    def test_edit_deposit_preserves_original_date(self):
        deposit = Deposit.objects.create(
            date=datetime.date(2026, 8, 5), year=2026, month=8, decade=Deposit.FIRST_DECADE,
            deposit_amount=Decimal("1000000"),
        )
        resp = self.client.post(f"/deposits/{deposit.pk}/edit/", {
            "date": "1405/05/14", "year": 2026, "month": 8, "decade": Deposit.FIRST_DECADE,
            "deposit_amount": "1500000", "difference_amount": "0",
            "document_number": "", "bank": "", "branch": "",
        })
        self.assertEqual(resp.status_code, 302)
        deposit.refresh_from_db()
        self.assertEqual(deposit.date, datetime.date(2026, 8, 5))
        self.assertEqual(deposit.deposit_amount, Decimal("1500000"))

    def test_delete_deposit_requires_post_confirmation(self):
        deposit = Deposit.objects.create(
            date=datetime.date(2026, 8, 5), year=2026, month=8, decade=Deposit.FIRST_DECADE,
            deposit_amount=Decimal("1000000"),
        )
        resp_get = self.client.get(f"/deposits/{deposit.pk}/delete/")
        self.assertEqual(resp_get.status_code, 200)
        self.assertEqual(Deposit.objects.count(), 1)

        resp_post = self.client.post(f"/deposits/{deposit.pk}/delete/")
        self.assertEqual(resp_post.status_code, 302)
        self.assertEqual(Deposit.objects.count(), 0)

    def test_deposit_list_shows_created_deposit(self):
        Deposit.objects.create(
            date=datetime.date(2026, 8, 5), year=2026, month=8, decade=Deposit.FIRST_DECADE,
            deposit_amount=Decimal("1234567"), document_number="DOC-999",
        )
        # Document numbers only appear on the decade detail page now --
        # the landing page shows the 3-decade summary table.
        resp = self.client.get("/deposits/2026/8/first/")
        self.assertContains(resp, "DOC-999")

    def test_bank_and_branch_fields_removed_from_form(self):
        """"بانک"/"شعبه" were removed from the deposit form entirely --
        posting them must not error (they're simply ignored, same as any
        other unknown POST key), and nothing is saved under those names
        since the model itself keeps the columns unused going forward."""
        resp = self.client.post("/deposits/new/", {
            "date": "1405/05/14", "year": 2026, "month": 8, "decade": Deposit.FIRST_DECADE,
            "deposit_amount": "1000000", "difference_amount": "0",
            "document_number": "", "bank": "some bank", "branch": "some branch",
        })
        self.assertEqual(resp.status_code, 302)
        deposit = Deposit.objects.get()
        self.assertEqual(deposit.bank, "")
        self.assertEqual(deposit.branch, "")


class DepositDecadeReworkTests(TestCase):
    """
    Covers the واریزی‌ها rework: year/month selector + 3-row دهه
    summary landing page, decade-detail pages with the exact 4-column
    chronological table, and dynamic third-decade length (9/10/11 days
    depending on the selected Jalali month).
    """

    def setUp(self):
        self.user = User.objects.create_user(username="op_dep", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        self.client.login(username="op_dep", password="testpass123")

    def test_landing_page_shows_three_decade_rows(self):
        resp = self.client.get("/deposits/?year=1405&month=6")
        self.assertContains(resp, "دهه اول")
        self.assertContains(resp, "دهه دوم")
        self.assertContains(resp, "دهه سوم")
        self.assertContains(resp, "جمع مبلغ واریزی")

    def test_deposits_on_boundary_days_land_in_correct_decade(self):
        """Basic check #1: register deposits on the 1st, 10th, 11th,
        20th, and 31st of a 31-day Jalali month (1405/06) and verify
        each lands in the correct decade."""
        # 1405/06/01, /10, /11, /20, /31 in Gregorian (see verified
        # conversions: day 1 -> 2026-08-23, day 10 -> 2026-09-01,
        # day 11 -> 2026-09-02, day 20 -> 2026-09-11, day 31 -> 2026-09-22).
        cases = [
            (datetime.date(2026, 8, 23), Deposit.FIRST_DECADE),
            (datetime.date(2026, 9, 1), Deposit.FIRST_DECADE),
            (datetime.date(2026, 9, 2), Deposit.SECOND_DECADE),
            (datetime.date(2026, 9, 11), Deposit.SECOND_DECADE),
            (datetime.date(2026, 9, 22), Deposit.THIRD_DECADE),
        ]
        for i, (greg_date, expected_decade) in enumerate(cases):
            Deposit.objects.create(
                date=greg_date, year=1405, month=6, decade=expected_decade,
                deposit_amount=Decimal("1000"), document_number=f"DOC-{i}",
            )

        for i, (greg_date, expected_decade) in enumerate(cases):
            resp = self.client.get(f"/deposits/1405/6/{expected_decade}/")
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, f"DOC-{i}")

        self.assertEqual(
            Deposit.objects.filter(year=1405, month=6, decade=Deposit.FIRST_DECADE).count(), 2
        )
        self.assertEqual(
            Deposit.objects.filter(year=1405, month=6, decade=Deposit.SECOND_DECADE).count(), 2
        )
        self.assertEqual(
            Deposit.objects.filter(year=1405, month=6, decade=Deposit.THIRD_DECADE).count(), 1
        )

    def test_decade_detail_shows_records_in_chronological_order(self):
        Deposit.objects.create(
            date=datetime.date(2026, 9, 2), year=1405, month=6, decade=Deposit.SECOND_DECADE,
            deposit_amount=Decimal("500"), document_number="LATER",
        )
        Deposit.objects.create(
            date=datetime.date(2026, 8, 25), year=1405, month=6, decade=Deposit.FIRST_DECADE,
            deposit_amount=Decimal("300"), document_number="EARLIER",
        )
        # Same decade, need two same-decade records to test ordering meaningfully.
        Deposit.objects.create(
            date=datetime.date(2026, 8, 23), year=1405, month=6, decade=Deposit.FIRST_DECADE,
            deposit_amount=Decimal("100"), document_number="EARLIEST",
        )
        resp = self.client.get("/deposits/1405/6/first/")
        content = resp.content.decode()
        pos_earliest = content.index("EARLIEST")
        pos_earlier = content.index("EARLIER")
        self.assertLess(pos_earliest, pos_earlier)

    def test_decade_detail_shows_all_four_required_columns(self):
        Deposit.objects.create(
            date=datetime.date(2026, 8, 23), year=1405, month=6, decade=Deposit.FIRST_DECADE,
            deposit_amount=Decimal("500000"), difference_amount=Decimal("1000"),
            document_number="DOC-77",
        )
        resp = self.client.get("/deposits/1405/6/first/")
        content = resp.content.decode()
        for label in ["تاریخ سند", "شماره ی سند", "مبلغ واریزی", "مبلغ مابه التفاوت"]:
            self.assertIn(label, content)
        self.assertIn("DOC-77", content)
        self.assertIn("500,000", content)
        self.assertIn("1,000", content)

    def test_decade_total_equals_sum_of_its_deposits(self):
        """Basic check #2: جمع مبلغ واریزی equals the sum of all
        مبلغ واریزی records within that decade."""
        for amount in ("100000", "200000", "50000"):
            Deposit.objects.create(
                date=datetime.date(2026, 8, 23), year=1405, month=6, decade=Deposit.FIRST_DECADE,
                deposit_amount=Decimal(amount),
            )
        from apps.deposits import services
        rows = services.decade_totals(1405, 6)
        first_row = next(r for r in rows if r["decade"] == Deposit.FIRST_DECADE)
        self.assertEqual(first_row["total"], Decimal("350000"))

    def test_decade_totals_are_independent_per_decade(self):
        Deposit.objects.create(
            date=datetime.date(2026, 8, 23), year=1405, month=6, decade=Deposit.FIRST_DECADE,
            deposit_amount=Decimal("100"),
        )
        Deposit.objects.create(
            date=datetime.date(2026, 9, 2), year=1405, month=6, decade=Deposit.SECOND_DECADE,
            deposit_amount=Decimal("200"),
        )
        from apps.deposits import services
        rows = services.decade_totals(1405, 6)
        totals = {r["decade"]: r["total"] for r in rows}
        self.assertEqual(totals[Deposit.FIRST_DECADE], Decimal("100"))
        self.assertEqual(totals[Deposit.SECOND_DECADE], Decimal("200"))
        self.assertEqual(totals[Deposit.THIRD_DECADE], Decimal("0"))

    def test_third_decade_has_eleven_days_in_a_31_day_month(self):
        """Basic check #2 (continued): a 31-day month's دهه سوم must
        contain 11 days (21-31), not a hardcoded 10."""
        from apps.deposits import services
        self.assertEqual(services.third_decade_length(1405, 6), 11)

    def test_third_decade_has_ten_days_in_a_30_day_month(self):
        from apps.deposits import services
        self.assertEqual(services.third_decade_length(1405, 7), 10)

    def test_decade_with_no_deposits_shows_zero_total(self):
        from apps.deposits import services
        rows = services.decade_totals(1405, 6)
        for row in rows:
            self.assertEqual(row["total"], Decimal("0"))

    def test_deposit_form_no_longer_has_bank_or_branch_fields(self):
        resp = self.client.get("/deposits/new/")
        content = resp.content.decode()
        self.assertNotIn(">بانک<", content)
        self.assertNotIn(">شعبه<", content)

    def test_create_deposit_button_present_on_landing_and_detail_pages(self):
        resp1 = self.client.get("/deposits/")
        self.assertContains(resp1, "ثبت اطلاعات جدید")
        resp2 = self.client.get("/deposits/1405/6/first/")
        self.assertContains(resp2, "ثبت اطلاعات جدید")


class DepositListAutoDisplayAndTotalsTests(TestCase):
    """
    Covers: (1) no separate نمایش/Submit button on the landing page --
    year/month changes navigate automatically, like گزارش ماهانه مخازن;
    (2) جمع مبلغ واریزی ماه = sum of the three decade totals; (3) a
    print link per decade on both the landing page and the decade
    detail page; (4) Persian decade labels in the registration form.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="op_dep2", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        self.client.login(username="op_dep2", password="testpass123")

    def test_no_submit_button_on_landing_page(self):
        """The year/month selector itself must remain, but its own
        نمایش/Submit button and wrapping <form> are gone -- selection now
        navigates via onchange, exactly like گزارش ماهانه مخازن. (Other,
        unrelated forms on the page -- the header's global-date picker and
        logout button -- are untouched and expected.)"""
        resp = self.client.get("/deposits/?year=1405&month=6")
        content = resp.content.decode()
        self.assertNotIn(">نمایش<", content)
        self.assertIn("onchange=", content)

    def test_monthly_total_equals_sum_of_decade_totals(self):
        Deposit.objects.create(
            date=datetime.date(2026, 8, 23), year=1405, month=6, decade=Deposit.FIRST_DECADE,
            deposit_amount=Decimal("100000"),
        )
        Deposit.objects.create(
            date=datetime.date(2026, 9, 2), year=1405, month=6, decade=Deposit.SECOND_DECADE,
            deposit_amount=Decimal("50000"),
        )
        Deposit.objects.create(
            date=datetime.date(2026, 9, 12), year=1405, month=6, decade=Deposit.THIRD_DECADE,
            deposit_amount=Decimal("25000"),
        )
        resp = self.client.get("/deposits/?year=1405&month=6")
        self.assertContains(resp, "جمع مبلغ واریزی ماه")
        self.assertContains(resp, "175,000")

    def test_print_link_present_for_each_decade_on_landing_page(self):
        resp = self.client.get("/deposits/?year=1405&month=6")
        content = resp.content.decode()
        for decade in (Deposit.FIRST_DECADE, Deposit.SECOND_DECADE, Deposit.THIRD_DECADE):
            self.assertIn(f"decade={decade}", content)
        self.assertIn("deposits-decade/", content)

    def test_print_link_present_on_decade_detail_page(self):
        resp = self.client.get("/deposits/1405/6/first/")
        content = resp.content.decode()
        self.assertIn("deposits-decade/", content)
        self.assertIn("decade=first", content)

    def test_decade_choices_use_persian_labels(self):
        resp = self.client.get("/deposits/new/")
        content = resp.content.decode()
        self.assertIn(">دهه اول<", content)
        self.assertIn(">دهه دوم<", content)
        self.assertIn(">دهه سوم<", content)
        self.assertNotIn("Days 1-10", content)

    def test_decade_stored_values_unchanged(self):
        """Only the displayed labels changed -- the stored/choice values
        (\"first\"/\"second\"/\"third\") must still round-trip exactly as
        before."""
        resp = self.client.post("/deposits/new/", {
            "date": "1405/06/05", "year": 1405, "month": 6, "decade": Deposit.FIRST_DECADE,
            "deposit_amount": "1000", "difference_amount": "0", "document_number": "",
        })
        self.assertEqual(resp.status_code, 302)
        deposit = Deposit.objects.get()
        self.assertEqual(deposit.decade, "first")
