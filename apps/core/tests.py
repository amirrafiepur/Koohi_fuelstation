import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.license.models import License
from apps.stations.models import Station, Product, Tank, Nozzle

from .display import format_number, persian_product_name, trim_trailing_zeros

User = get_user_model()


class DashboardSmokeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date.today(), duration_days=365)
        station = Station.objects.create(name="140 Jahan Pour", province="Razavi Khorasan", city="Mashhad")
        regular = Product.objects.create(name="Regular")
        super_ = Product.objects.create(name="Super")
        self.regular_tank = Tank.objects.create(station=station, product=regular, capacity=50000)
        self.super_tank = Tank.objects.create(station=station, product=super_, capacity=30000)
        for n in list(range(1, 19)) + [25, 26]:
            Nozzle.objects.create(tank=self.regular_tank, number=n)
        for n in range(19, 25):
            Nozzle.objects.create(tank=self.super_tank, number=n)

    def test_login_page_loads(self):
        resp = self.client.get("/accounts/login/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="username"')

    def test_login_prefills_last_used_username(self):
        self.client.post("/accounts/login/", {"username": "op1", "password": "testpass123"})
        self.client.logout()
        resp = self.client.get("/accounts/login/")
        self.assertContains(resp, 'value="op1"')

    def test_successful_login_redirects_to_dashboard(self):
        resp = self.client.post(
            "/accounts/login/", {"username": "op1", "password": "testpass123"}, follow=True
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "کارکرد مخازن")
        self.assertContains(resp, "کارکرد نازل\u200cها")

    def test_escape_navigation_script_present_site_wide(self):
        """Task 4B: Escape returns to the previous view/state. Verified
        structurally (this project has no JS test runner, same
        verification level as its other JS keyboard shortcuts): the
        listener is present, targets Escape, uses the browser's own
        history (the existing navigation architecture -- every filter/
        selection in this app is already a URL, so history.back() IS
        "the previous state"), and is guarded against interfering with
        inputs/selects/editable content."""
        self.client.login(username="op1", password="testpass123")
        resp = self.client.get("/")
        content = resp.content.decode()
        self.assertIn("'Escape'", content)
        self.assertIn("history.back()", content)
        self.assertIn("keydown", content)
        self.assertIn("'input'", content)
        self.assertIn("'select'", content)
        self.assertIn("isContentEditable", content)

    def test_escape_script_present_on_other_sections_too(self):
        """Confirms this lives in the shared base template, not just the
        dashboard -- i.e. it genuinely supports navigation between
        sections, not only within one page."""
        self.client.login(username="op1", password="testpass123")
        for url in ["/seals/", "/deposits/", "/statement/"]:
            resp = self.client.get(url)
            self.assertIn("history.back()", resp.content.decode())

    def test_dashboard_shows_all_26_nozzles(self):
        self.client.login(username="op1", password="testpass123")
        resp = self.client.get("/")
        content = resp.content.decode()
        rendered_count = content.count('class="nozzle-grid__item"')
        self.assertEqual(rendered_count, 26)

    def test_dashboard_shows_license_valid_badge(self):
        self.client.login(username="op1", password="testpass123")
        resp = self.client.get("/")
        self.assertContains(resp, "لایسنس تا 365 روز دیگر معتبر است")

    def test_anonymous_user_redirected_to_login(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp.url)

    def test_expired_license_redirects_to_renewal(self):
        License.objects.all().delete()
        License.objects.create(
            start_date=datetime.date.today() - datetime.timedelta(days=400),
            duration_days=365,
        )
        self.client.login(username="op1", password="testpass123")
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/license/renew/", resp.url)

    def test_renewal_page_reachable_even_when_expired(self):
        License.objects.all().delete()
        License.objects.create(
            start_date=datetime.date.today() - datetime.timedelta(days=400),
            duration_days=365,
        )
        self.client.login(username="op1", password="testpass123")
        resp = self.client.get("/license/renew/")
        self.assertEqual(resp.status_code, 200)

    def test_correct_renewal_password_restores_access(self):
        License.objects.all().delete()
        License.objects.create(
            start_date=datetime.date.today() - datetime.timedelta(days=400),
            duration_days=365,
        )
        self.client.login(username="op1", password="testpass123")
        resp = self.client.post(
            "/license/renew/", {"password": "769112005a@"}, follow=True
        )
        self.assertContains(resp, "کارکرد مخازن")

    def test_each_nozzle_button_links_to_its_own_ledger(self):
        """
        Clicking a nozzle on the dashboard must take the operator to
        گزارش کارکرد هر نازل for THAT nozzle -- not to the sales entry
        screen. Checked for every one of the 26 seeded nozzles, not just
        one, since each button's link is built from that nozzle's own id.
        """
        self.client.login(username="op1", password="testpass123")
        resp = self.client.get("/")
        content = resp.content.decode()

        for nozzle in Nozzle.objects.all():
            expected_href = f'/reports/nozzle-ledger/?nozzle_id={nozzle.id}'
            self.assertIn(expected_href, content)

        # The old destination must be gone entirely.
        self.assertNotIn('sales/invoices/', content)

    def test_clicking_a_nozzle_shows_that_exact_nozzles_report(self):
        nozzle_1 = Nozzle.objects.get(tank=self.regular_tank, number=1)
        nozzle_19 = Nozzle.objects.get(tank=self.super_tank, number=19)

        self.client.login(username="op1", password="testpass123")

        resp1 = self.client.get(f"/reports/nozzle-ledger/?nozzle_id={nozzle_1.id}")
        self.assertContains(resp1, "نازل 1 (")

        resp19 = self.client.get(f"/reports/nozzle-ledger/?nozzle_id={nozzle_19.id}")
        self.assertContains(resp19, "نازل 19 (")


class DisplayHelpersTests(TestCase):
    """
    apps/core/display.py: Product.name -> Persian display label, without
    touching the stored value. Stored "Regular"/"Super" are unaffected;
    an unmapped name (a future third product) passes through unchanged.
    """

    def test_known_product_names_map_to_persian(self):
        self.assertEqual(persian_product_name("Regular"), "بنزین معمولی")
        self.assertEqual(persian_product_name("Super"), "بنزین سوپر")

    def test_unmapped_product_name_passes_through_unchanged(self):
        self.assertEqual(persian_product_name("Diesel"), "Diesel")

    def test_persian_product_template_filter(self):
        from django.template import Context, Template

        rendered = Template("{% load display_tags %}{{ name|persian_product }}").render(
            Context({"name": "Super"})
        )
        self.assertEqual(rendered, "بنزین سوپر")


class TrimTrailingZerosTests(TestCase):
    """
    apps/core/display.py:trim_trailing_zeros() -- removes an unnecessary
    trailing .00 (or similar) from a DISPLAYED number only; the stored
    DecimalField value itself is never touched by this (it's a pure
    formatting function applied after reading a value for display).
    """

    def test_whole_number_with_trailing_zero_decimals_is_trimmed(self):
        self.assertEqual(trim_trailing_zeros(Decimal("35.00")), "35")
        self.assertEqual(trim_trailing_zeros(Decimal("100.00")), "100")

    def test_meaningful_fractional_values_are_preserved(self):
        self.assertEqual(trim_trailing_zeros(Decimal("1.5")), "1.5")
        self.assertEqual(trim_trailing_zeros(Decimal("1.25")), "1.25")
        self.assertEqual(trim_trailing_zeros(Decimal("1.10")), "1.1")

    def test_zero_and_negative_values(self):
        self.assertEqual(trim_trailing_zeros(Decimal("0.00")), "0")
        self.assertEqual(trim_trailing_zeros(Decimal("-5.00")), "-5")

    def test_never_produces_scientific_notation(self):
        self.assertEqual(trim_trailing_zeros(Decimal("1200.00")), "1200")
        self.assertNotIn("E", trim_trailing_zeros(Decimal("100.00")).upper())

    def test_non_numeric_values_pass_through_unchanged(self):
        self.assertIsNone(trim_trailing_zeros(None))
        self.assertEqual(trim_trailing_zeros(""), "")

    def test_trim_zeros_template_filter(self):
        from django.template import Context, Template

        rendered = Template("{% load display_tags %}{{ value|trim_zeros }}").render(
            Context({"value": Decimal("35.00")})
        )
        self.assertEqual(rendered, "35")


class StationDisplayTests(TestCase):
    """
    Product names and the station name/location shown in the UI must be
    Persian, while the underlying Station/Product rows keep their
    original seeded values (see apps/stations/management/commands/
    seed_station.py and apps/printing/services.get_station_metadata).
    """

    def setUp(self):
        self.user = User.objects.create_user(username="op_disp", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        self.station = Station.objects.create(
            name="140 Jahan Pour", province="Razavi Khorasan", city="Mashhad",
        )
        regular = Product.objects.create(name="Regular")
        Tank.objects.create(station=self.station, product=regular, capacity=50000)
        self.client.login(username="op_disp", password="testpass123")

    def test_dashboard_shows_persian_product_name_not_english(self):
        resp = self.client.get("/")
        content = resp.content.decode()
        self.assertIn("بنزین معمولی", content)
        self.assertNotIn(">Regular<", content)

    def test_dashboard_station_header_uses_correct_spelling(self):
        resp = self.client.get("/")
        content = resp.content.decode()
        self.assertIn("جهانی\u200cپور", content)
        self.assertNotIn("جهانی پور", content)  # plain space, the old typo'd rendering
        self.assertNotIn("جهان\u200cپور", content)  # missing "ی"

    def test_stored_db_values_unchanged(self):
        self.station.refresh_from_db()
        self.assertEqual(self.station.name, "140 Jahan Pour")
        self.assertEqual(self.station.province, "Razavi Khorasan")
        self.assertEqual(self.station.city, "Mashhad")

    def test_get_station_metadata_returns_persian_for_known_seed(self):
        from apps.printing.services import get_station_metadata

        meta = get_station_metadata()
        self.assertEqual(meta["name"], "جایگاه جهانی\u200cپور ۱۴۰")
        self.assertEqual(meta["province"], "خراسان رضوی")
        self.assertEqual(meta["city"], "مشهد")

    def test_get_station_metadata_falls_back_for_unknown_station(self):
        from apps.printing.services import get_station_metadata

        self.station.name = "Some Other Station"
        self.station.province = "X"
        self.station.city = "Y"
        self.station.save()

        meta = get_station_metadata()
        self.assertEqual(meta["name"], "Some Other Station")
        self.assertEqual(meta["province"], "X")
        self.assertEqual(meta["city"], "Y")

    def test_pdf_header_source_html_is_persian(self):
        """Renders the actual base_print.html header block (the exact
        HTML WeasyPrint turns into PDF) without needing weasyprint
        installed."""
        from django.template import engines

        django_engine = engines["django"]
        template = django_engine.from_string(
            "{% extends 'printing/base_print.html' %}"
            "{% block report_body %}{% endblock %}"
        )
        html = template.render({
            "station": {"name": "جایگاه جهانی\u200cپور ۱۴۰", "province": "خراسان رضوی", "city": "مشهد"},
        })
        self.assertIn("جایگاه جهانی\u200cپور ۱۴۰", html)
        self.assertIn("مشهد، خراسان رضوی", html)


class FormatNumberTests(TestCase):
    """Task 1 Part B: thousands separators on top of zero-trimming."""

    def test_integers_are_grouped_in_threes_from_the_right(self):
        for raw, expected in [
            (0, "0"), (7, "7"), (999, "999"), (1000, "1,000"), (123456, "123,456"),
            (123456789, "123,456,789"), (Decimal("1234567.00"), "1,234,567"),
            (Decimal("100"), "100"), (Decimal("1000000"), "1,000,000"),
        ]:
            self.assertEqual(format_number(raw), expected, raw)

    def test_decimals_keep_precision_and_only_the_integer_part_is_grouped(self):
        for raw, expected in [
            (Decimal("1234.50"), "1,234.5"), (Decimal("1234.25"), "1,234.25"),
            (Decimal("1234567.125"), "1,234,567.125"), (Decimal("0.25"), "0.25"),
            (Decimal("1.5"), "1.5"), (Decimal("999.99"), "999.99"),
            (Decimal("1000.01"), "1,000.01"),
        ]:
            self.assertEqual(format_number(raw), expected, raw)

    def test_negative_numbers(self):
        self.assertEqual(format_number(Decimal("-1234567.50")), "-1,234,567.5")
        self.assertEqual(format_number(Decimal("-12")), "-12")
        self.assertEqual(format_number(Decimal("-0.5")), "-0.5")

    def test_non_numeric_values_pass_through_unchanged(self):
        self.assertIsNone(format_number(None))
        self.assertEqual(format_number(""), "")
        self.assertEqual(format_number("—"), "—")
        self.assertEqual(format_number("abc"), "abc")

    def test_string_input_and_stored_value_untouched(self):
        self.assertEqual(format_number("1234567.00"), "1,234,567")
        d = Decimal("1234567.00")
        format_number(d)
        self.assertEqual(d, Decimal("1234567.00"))
        self.assertEqual(str(d), "1234567.00")
