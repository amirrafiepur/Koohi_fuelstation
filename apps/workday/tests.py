"""
Chronology tests -- covering the corrected "accounting month start" rule
and basic future/past-date enforcement.
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.license.models import License
from apps.sales.models import NozzleSale, SalesInvoice
from apps.stations.models import Nozzle, Product, Station, Tank
from apps.workday import services
from apps.workday.models import DailyWorkingDay

User = get_user_model()


class AccountingStartDateTests(TestCase):
    def test_no_license_means_no_accounting_start(self):
        self.assertIsNone(services.get_accounting_start_date())

    def test_mid_month_activation_sets_start_to_jalali_month_day_one(self):
        # 2026-08-15 is Jalali 1405/05/24 -- the accounting start must be
        # day 1 of THAT Jalali month (1405/05/01), which is Gregorian
        # 2026-07-23, not the 1st of the Gregorian calendar month
        # (2026-08-01).
        License.objects.create(start_date=datetime.date(2026, 8, 15), duration_days=365)
        self.assertEqual(
            services.get_accounting_start_date(), datetime.date(2026, 7, 23)
        )

    def test_jalali_month_day_one_activation_sets_start_to_same_day(self):
        # 2026-08-23 is Jalali 1405/06/01 -- already day 1 of its Jalali
        # month, so the accounting start is that same date.
        License.objects.create(start_date=datetime.date(2026, 8, 23), duration_days=365)
        self.assertEqual(
            services.get_accounting_start_date(), datetime.date(2026, 8, 23)
        )


class CanEnterDateTests(TestCase):
    def setUp(self):
        # 2026-08-15 is Jalali 1405/05/24; accounting start is the 1st of
        # that Jalali month, Gregorian 2026-07-23 (see AccountingStartDateTests).
        License.objects.create(start_date=datetime.date(2026, 8, 15), duration_days=365)

    def test_future_date_rejected(self):
        tomorrow = timezone.localdate() + datetime.timedelta(days=1)
        allowed, reason = services.can_enter_date(tomorrow)
        self.assertFalse(allowed)
        self.assertIn("آینده", reason)

    def test_date_before_accounting_start_rejected(self):
        allowed, reason = services.can_enter_date(datetime.date(2026, 7, 22))
        self.assertFalse(allowed)

    def test_date_on_accounting_start_allowed(self):
        allowed, _ = services.can_enter_date(datetime.date(2026, 7, 23))
        self.assertTrue(allowed)

    def test_date_between_start_and_activation_allowed(self):
        allowed, _ = services.can_enter_date(datetime.date(2026, 8, 10))
        self.assertTrue(allowed)


class IncompleteDaysTests(TestCase):
    def test_mid_month_activation_creates_missing_days_from_jalali_month_start(self):
        # 2026-08-15 is Jalali 1405/05/24; accounting start is Gregorian
        # 2026-07-23 (Jalali 1405/05/01) -- 24 days before the up_to date.
        License.objects.create(start_date=datetime.date(2026, 8, 15), duration_days=365)
        missing = services.get_incomplete_days(up_to=datetime.date(2026, 8, 15))
        self.assertEqual(missing[0], datetime.date(2026, 7, 23))
        self.assertEqual(missing[-1], datetime.date(2026, 8, 15))
        self.assertEqual(len(missing), 24)

    def test_closing_a_day_removes_it_from_missing_list(self):
        License.objects.create(start_date=datetime.date(2026, 8, 15), duration_days=365)
        services.close_day(datetime.date(2026, 7, 23))
        missing = services.get_incomplete_days(up_to=datetime.date(2026, 7, 24))
        self.assertNotIn(datetime.date(2026, 7, 23), missing)
        self.assertIn(datetime.date(2026, 7, 24), missing)

    def test_deleting_reopens_the_day(self):
        License.objects.create(start_date=datetime.date(2026, 8, 15), duration_days=365)
        services.close_day(datetime.date(2026, 7, 23))
        services.reopen_day_on_delete(datetime.date(2026, 7, 23))
        missing = services.get_incomplete_days(up_to=datetime.date(2026, 7, 23))
        self.assertIn(datetime.date(2026, 7, 23), missing)


class LastDayOfMonthTests(TestCase):
    def test_february_non_leap(self):
        self.assertEqual(
            services.last_day_of_month(datetime.date(2026, 2, 5)),
            datetime.date(2026, 2, 28),
        )

    def test_february_leap(self):
        self.assertEqual(
            services.last_day_of_month(datetime.date(2028, 2, 5)),
            datetime.date(2028, 2, 29),
        )

    def test_31_day_month(self):
        self.assertEqual(
            services.last_day_of_month(datetime.date(2026, 8, 5)),
            datetime.date(2026, 8, 31),
        )


class NozzleBasedCompletionTests(TestCase):
    """
    The actual bug: a day must be recognized as complete once every
    registered Nozzle has a NozzleSale row for it -- WITHOUT requiring
    close_day() to have been called. Previously get_incomplete_days()
    only ever looked at DailyWorkingDay.status, which no production code
    path ever set, so every day stayed "missing" forever even after all
    nozzles were entered.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="op_wd", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 23), duration_days=365)
        # 2026-08-23 is Jalali 1405/06/01 -- accounting start == that
        # same date (see AccountingStartDateTests), keeping this fixture
        # independent of the mid-month-activation offset math.
        station = Station.objects.create(name="S_wd", province="P", city="C")
        product = Product.objects.create(name="Regular")
        self.tank = Tank.objects.create(station=station, product=product, capacity=50000)
        self.nozzles = [Nozzle.objects.create(tank=self.tank, number=n) for n in (1, 2, 3)]
        self.day = datetime.date(2026, 8, 23)

    def _fill_all_nozzles(self, date):
        wd, _ = DailyWorkingDay.objects.get_or_create(date=date)
        invoice = SalesInvoice.objects.create(working_day=wd, operator=self.user)
        for nozzle in self.nozzles:
            NozzleSale.objects.create(
                sales_invoice=invoice, nozzle=nozzle,
                previous_meter=Decimal("0"), new_meter=Decimal("10"),
                test=Decimal("0"), sales_rate=Decimal("1200"),
            )
        return wd

    def test_day_with_all_nozzles_filled_is_not_missing_even_without_close_day(self):
        self._fill_all_nozzles(self.day)
        missing = services.get_incomplete_days(up_to=self.day)
        self.assertNotIn(self.day, missing)

    def test_day_with_some_nozzles_missing_is_still_incomplete(self):
        wd, _ = DailyWorkingDay.objects.get_or_create(date=self.day)
        invoice = SalesInvoice.objects.create(working_day=wd, operator=self.user)
        # Only 2 of 3 nozzles registered.
        for nozzle in self.nozzles[:2]:
            NozzleSale.objects.create(
                sales_invoice=invoice, nozzle=nozzle,
                previous_meter=Decimal("0"), new_meter=Decimal("10"),
                test=Decimal("0"), sales_rate=Decimal("1200"),
            )
        missing = services.get_incomplete_days(up_to=self.day)
        self.assertIn(self.day, missing)

    def test_day_with_no_sales_invoice_at_all_is_incomplete(self):
        missing = services.get_incomplete_days(up_to=self.day)
        self.assertIn(self.day, missing)

    def test_status_complete_still_counts_as_complete(self):
        """Backward compatibility: a day explicitly closed via
        close_day() (even with no nozzle data) still counts as
        complete -- the nozzle check only ever widens completeness,
        never narrows it."""
        services.close_day(self.day)
        missing = services.get_incomplete_days(up_to=self.day)
        self.assertNotIn(self.day, missing)

    def test_next_required_date_skips_a_fully_entered_day(self):
        self._fill_all_nozzles(self.day)
        next_day = self.day + datetime.timedelta(days=1)
        next_required = services.get_next_required_date()
        self.assertEqual(next_required, next_day)

    def test_no_missing_days_means_next_required_date_is_none(self):
        self._fill_all_nozzles(self.day)
        # Accounting start == today in this fixture, so filling the one
        # required day leaves nothing missing.
        from unittest import mock
        with mock.patch.object(services, "get_today", return_value=self.day):
            self.assertIsNone(services.get_next_required_date())

    def test_saving_the_last_nozzle_via_the_view_closes_the_day(self):
        """End-to-end: the نازل entry view itself must leave the day
        correctly recognized as complete, not just the service function
        in isolation."""
        self.client.login(username="op_wd", password="testpass123")
        wd, _ = DailyWorkingDay.objects.get_or_create(date=self.day)
        for nozzle in self.nozzles[:-1]:
            self.client.post(
                f"/sales/invoices/{self.day.isoformat()}/nozzle/{nozzle.number}/",
                {"previous_meter": "0", "new_meter": "10", "test": "0", "sales_rate": "1200"},
            )
        last_nozzle = self.nozzles[-1]
        resp = self.client.post(
            f"/sales/invoices/{self.day.isoformat()}/nozzle/{last_nozzle.number}/",
            {"previous_meter": "0", "new_meter": "10", "test": "0", "sales_rate": "1200"},
        )
        self.assertEqual(resp.status_code, 302)
        missing = services.get_incomplete_days(up_to=self.day)
        self.assertNotIn(self.day, missing)


class DashboardNotificationTests(TestCase):
    """The dashboard notification and the global Date Control default,
    end to end, for both the "has missing days" and "fully caught up"
    cases."""

    def setUp(self):
        self.user = User.objects.create_user(username="op_dash", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 23), duration_days=365)
        station = Station.objects.create(name="S_dash", province="P", city="C")
        product = Product.objects.create(name="Regular")
        self.tank = Tank.objects.create(station=station, product=product, capacity=50000)
        self.nozzle = Nozzle.objects.create(tank=self.tank, number=1)
        self.day = datetime.date(2026, 8, 23)
        self.client.login(username="op_dash", password="testpass123")

    def test_notification_shown_and_points_at_earliest_missing_day(self):
        resp = self.client.get("/")
        content = resp.content.decode()
        self.assertIn("روز کاری ناقص", content)

    def test_notification_hidden_once_every_day_is_complete(self):
        from unittest import mock

        wd, _ = DailyWorkingDay.objects.get_or_create(date=self.day)
        invoice = SalesInvoice.objects.create(working_day=wd, operator=self.user)
        NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=self.nozzle,
            previous_meter=Decimal("0"), new_meter=Decimal("10"),
            test=Decimal("0"), sales_rate=Decimal("1200"),
        )
        from apps.workday import services as workday_services
        with mock.patch.object(workday_services, "get_today", return_value=self.day):
            resp = self.client.get("/")
        content = resp.content.decode()
        self.assertNotIn("روز کاری ناقص", content)

    def test_global_date_control_defaults_to_earliest_missing_day(self):
        from apps.workday import services as workday_services
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.session = self.client.session
        self.assertEqual(workday_services.get_global_date(request), self.day)

    def test_global_date_control_defaults_to_today_when_nothing_missing(self):
        from unittest import mock

        wd, _ = DailyWorkingDay.objects.get_or_create(date=self.day)
        invoice = SalesInvoice.objects.create(working_day=wd, operator=self.user)
        NozzleSale.objects.create(
            sales_invoice=invoice, nozzle=self.nozzle,
            previous_meter=Decimal("0"), new_meter=Decimal("10"),
            test=Decimal("0"), sales_rate=Decimal("1200"),
        )
        from apps.workday import services as workday_services
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.session = self.client.session
        with mock.patch.object(workday_services, "get_today", return_value=self.day):
            self.assertEqual(workday_services.get_global_date(request), self.day)
