import datetime

from django.test import TestCase
from django.utils import timezone

from apps.license import services
from apps.license.models import License


class LicenseValidityTests(TestCase):
    def test_no_license_is_invalid(self):
        self.assertFalse(services.is_license_valid())

    def test_freshly_activated_license_is_valid(self):
        services.activate_license(duration_days=365)
        self.assertTrue(services.is_license_valid())

    def test_license_valid_for_365_days(self):
        start = timezone.localdate() - datetime.timedelta(days=364)
        License.objects.create(start_date=start, duration_days=365)
        self.assertTrue(services.is_license_valid())

    def test_license_expired_after_365_days(self):
        start = timezone.localdate() - datetime.timedelta(days=366)
        License.objects.create(start_date=start, duration_days=365)
        self.assertFalse(services.is_license_valid())

    def test_seven_day_warning_threshold(self):
        start = timezone.localdate() - datetime.timedelta(days=359)  # 6 days remain
        License.objects.create(start_date=start, duration_days=365)
        self.assertTrue(services.should_show_expiry_warning())

    def test_no_warning_when_more_than_seven_days_remain(self):
        start = timezone.localdate() - datetime.timedelta(days=350)  # 15 days remain
        License.objects.create(start_date=start, duration_days=365)
        self.assertFalse(services.should_show_expiry_warning())

    def test_no_warning_once_expired(self):
        start = timezone.localdate() - datetime.timedelta(days=400)
        License.objects.create(start_date=start, duration_days=365)
        self.assertFalse(services.should_show_expiry_warning())


class LicenseRenewalTests(TestCase):
    def setUp(self):
        expired_start = timezone.localdate() - datetime.timedelta(days=400)
        self.license = License.objects.create(start_date=expired_start, duration_days=365)

    def test_correct_password_renews_license(self):
        result = services.renew_license("769112005a@")
        self.assertTrue(result)
        self.license.refresh_from_db()
        self.assertEqual(self.license.start_date, timezone.localdate())
        self.assertTrue(services.is_license_valid())

    def test_incorrect_password_does_not_renew(self):
        result = services.renew_license("wrong-password")
        self.assertFalse(result)
        self.license.refresh_from_db()
        self.assertNotEqual(self.license.start_date, timezone.localdate())
        self.assertFalse(services.is_license_valid())

    def test_renewal_password_hash_is_not_the_plaintext(self):
        from apps.license.models import RENEWAL_PASSWORD_HASH
        self.assertNotEqual(RENEWAL_PASSWORD_HASH, "769112005a@")
        self.assertTrue(RENEWAL_PASSWORD_HASH.startswith("pbkdf2_"))
