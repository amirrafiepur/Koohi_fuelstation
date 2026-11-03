from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Operator
from apps.license.models import License
from apps.license import services as license_services


User = get_user_model()


class SingleOperatorFirstRunTests(TestCase):
    def test_fresh_install_allows_first_setup(self):
        response = self.client.get(reverse("accounts:first_setup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "اولین حساب کاربری")
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(License.objects.count(), 0)

    def test_first_setup_creates_only_operator_and_starts_license(self):
        before = timezone.localdate()
        response = self.client.post(
            reverse("accounts:first_setup"),
            {
                "setup_password": "769112005a",
                "username": "operator", "password1": "StrongPass123!", "password2": "StrongPass123!",
                "security_question": "رنگ مورد علاقه شما چیست؟", "security_answer": "آبی",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 1)
        user = User.objects.get(username="operator")
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertTrue(Operator.objects.filter(user=user).exists())
        operator = Operator.objects.get(user=user)
        self.assertEqual(operator.security_question, "رنگ مورد علاقه شما چیست؟")
        self.assertTrue(operator.check_security_answer("آبی"))
        self.assertEqual(License.objects.count(), 1)
        self.assertEqual(License.objects.get().start_date, before)
        self.assertTrue(license_services.is_license_valid())
        self.assertIn("کارکرد مخازن", response.content.decode())

    def test_first_setup_does_not_reset_an_existing_license(self):
        user = User.objects.create_user(username="operator", password="StrongPass123!")
        Operator.objects.create(user=user, security_question="سوال آزمایشی؟", security_answer_hash="x")
        old_start = timezone.localdate() - timezone.timedelta(days=30)
        License.objects.create(start_date=old_start, duration_days=365)

        response = self.client.post(
            reverse("accounts:first_setup"),
            {"username": "second", "password1": "StrongPass123!", "password2": "StrongPass123!"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(License.objects.get().start_date, old_start)
        self.assertEqual(User.objects.count(), 1)

    def test_first_setup_is_unavailable_after_first_account(self):
        user = User.objects.create_user(username="operator", password="StrongPass123!")
        Operator.objects.create(user=user, security_question="سوال آزمایشی؟", security_answer_hash="x")
        License.objects.create(start_date=timezone.localdate(), duration_days=365)

        response = self.client.get(reverse("accounts:first_setup"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/accounts/login/"))

    def test_second_account_cannot_be_created_through_first_setup(self):
        User.objects.create_user(username="operator", password="StrongPass123!")
        License.objects.create(start_date=timezone.localdate(), duration_days=365)

        response = self.client.post(
            reverse("accounts:first_setup"),
            {"username": "second", "password1": "StrongPass123!", "password2": "StrongPass123!"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(User.objects.filter(username="second").exists())

    def test_login_is_available_on_fresh_install_without_license(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)

    def test_first_setup_activates_license_only_once(self):
        self.client.post(
            reverse("accounts:first_setup"),
            {
                "setup_password": "769112005a",
                "username": "operator", "password1": "StrongPass123!", "password2": "StrongPass123!",
                "security_question": "رنگ مورد علاقه شما چیست؟", "security_answer": "آبی",
            },
        )
        first_start = License.objects.get().start_date
        license_services.activate_license(as_of=first_start + timezone.timedelta(days=10))
        self.assertEqual(License.objects.count(), 1)
        self.assertEqual(License.objects.get().start_date, first_start)

    def test_renewal_without_a_license_does_not_activate_one(self):
        self.assertFalse(license_services.renew_license("any-password"))
        self.assertEqual(License.objects.count(), 0)

    def test_login_does_not_create_a_user(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "operator", "password": "StrongPass123!"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 0)


class PasswordRecoveryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="operator", password="OldPass123!")
        self.operator = Operator(user=self.user, security_question="رنگ مورد علاقه شما چیست؟")
        self.operator.set_security_answer("آبی")
        self.operator.save()

    def test_security_answer_is_never_stored_in_plaintext(self):
        self.assertNotEqual(self.operator.security_answer_hash, "آبی")
        self.assertTrue(self.operator.security_answer_hash.startswith("pbkdf2_"))

    def test_forgot_password_shows_the_stored_question(self):
        response = self.client.get(reverse("accounts:forgot_password"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "رنگ مورد علاقه شما چیست؟")

    def test_correct_answer_redirects_to_reset_password(self):
        response = self.client.post(
            reverse("accounts:forgot_password"), {"answer": "آبی"}
        )
        self.assertRedirects(response, reverse("accounts:reset_password"))
        self.assertTrue(self.client.session.get("password_recovery_verified"))

    def test_wrong_answer_does_not_grant_access(self):
        response = self.client.post(
            reverse("accounts:forgot_password"), {"answer": "قرمز"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "پاسخ صحیح نیست")
        self.assertFalse(self.client.session.get("password_recovery_verified"))

    def test_reset_password_unreachable_without_verified_session(self):
        response = self.client.get(reverse("accounts:reset_password"))
        self.assertRedirects(response, reverse("accounts:forgot_password"))

    def test_reset_password_unreachable_by_posting_directly(self):
        # Even a well-formed POST must not work without first passing the
        # security question this session.
        response = self.client.post(
            reverse("accounts:reset_password"),
            {"new_password1": "BrandNewPass123!", "new_password2": "BrandNewPass123!"},
        )
        self.assertRedirects(response, reverse("accounts:forgot_password"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldPass123!"))

    def test_full_recovery_flow_changes_password(self):
        self.client.post(reverse("accounts:forgot_password"), {"answer": "آبی"})
        response = self.client.post(
            reverse("accounts:reset_password"),
            {"new_password1": "BrandNewPass123!", "new_password2": "BrandNewPass123!"},
        )
        self.assertRedirects(response, reverse("accounts:login"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNewPass123!"))
        self.assertFalse(self.user.check_password("OldPass123!"))

    def test_verified_session_is_consumed_after_successful_reset(self):
        self.client.post(reverse("accounts:forgot_password"), {"answer": "آبی"})
        self.client.post(
            reverse("accounts:reset_password"),
            {"new_password1": "BrandNewPass123!", "new_password2": "BrandNewPass123!"},
        )
        # A second reset attempt must require answering the question again.
        response = self.client.get(reverse("accounts:reset_password"))
        self.assertRedirects(response, reverse("accounts:forgot_password"))

    def test_can_log_in_with_new_password_after_recovery(self):
        self.client.post(reverse("accounts:forgot_password"), {"answer": "آبی"})
        self.client.post(
            reverse("accounts:reset_password"),
            {"new_password1": "BrandNewPass123!", "new_password2": "BrandNewPass123!"},
        )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "operator", "password": "BrandNewPass123!"},
        )
        # A successful login redirects away from the login page (the exact
        # destination depends on license state, which this test doesn't
        # set up) -- 200 here would mean the login form was re-shown,
        # i.e. login failed.
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.url, reverse("accounts:login"))


class SetupPasswordProtectionTests(TestCase):
    """
    راه‌اندازی اولیه setup-password gate: correct password required to
    create the first account, wrong password blocks it and is counted
    persistently (survives "restart" -- i.e. a fresh request/process,
    simulated here by never relying on session state), and the 10th
    wrong attempt permanently locks setup. Distinct from, and must not
    affect, the license renewal password.
    """

    CORRECT = "769112005a"

    def _post(self, **overrides):
        data = {
            "setup_password": self.CORRECT,
            "username": "operator", "password1": "StrongPass123!", "password2": "StrongPass123!",
            "security_question": "رنگ مورد علاقه شما چیست؟", "security_answer": "آبی",
        }
        data.update(overrides)
        return self.client.post(reverse("accounts:first_setup"), data)

    def test_correct_password_creates_the_account(self):
        response = self._post()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(License.objects.count(), 1)

    def test_wrong_password_blocks_account_creation(self):
        response = self._post(setup_password="wrong-password")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(License.objects.count(), 0)
        self.assertContains(response, "رمز راه‌اندازی نادرست است")

    def test_setup_password_never_appears_in_the_page(self):
        response = self.client.get(reverse("accounts:first_setup"))
        self.assertNotIn(self.CORRECT, response.content.decode())
        response2 = self._post(setup_password="wrong-password")
        self.assertNotIn(self.CORRECT, response2.content.decode())

    def test_wrong_password_increments_persistent_counter(self):
        from apps.core.models import AppConfig

        self._post(setup_password="wrong-1")
        self.assertEqual(AppConfig.get_solo().setup_failed_attempts, 1)
        self._post(setup_password="wrong-2")
        self.assertEqual(AppConfig.get_solo().setup_failed_attempts, 2)

    def test_correct_password_does_not_increment_counter(self):
        from apps.core.models import AppConfig

        self._post()
        self.assertEqual(AppConfig.get_solo().setup_failed_attempts, 0)

    def test_tenth_wrong_attempt_permanently_locks_setup(self):
        from apps.core.models import AppConfig

        for _ in range(9):
            self._post(setup_password="wrong")
        self.assertFalse(AppConfig.get_solo().setup_locked)

        response = self._post(setup_password="wrong")  # 10th
        self.assertTrue(AppConfig.get_solo().setup_locked)
        self.assertEqual(AppConfig.get_solo().setup_failed_attempts, 10)
        self.assertEqual(User.objects.count(), 0)
        self.assertContains(response, "غیرفعال شده است")

    def test_locked_setup_rejects_even_the_correct_password(self):
        from apps.core.models import AppConfig

        config = AppConfig.get_solo()
        config.setup_locked = True
        config.setup_failed_attempts = 10
        config.save()

        response = self._post()  # correct password
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 0)
        self.assertContains(response, "غیرفعال شده است")

    def test_locked_setup_blocks_even_a_get_request(self):
        from apps.core.models import AppConfig

        config = AppConfig.get_solo()
        config.setup_locked = True
        config.setup_failed_attempts = 10
        config.save()

        response = self.client.get(reverse("accounts:first_setup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "غیرفعال شده است")
        self.assertNotContains(response, 'name="username"')

    def test_lock_and_counter_persist_in_database_not_session(self):
        """Simulates a restart: a fresh test client has no cookies/session
        at all, so if the lock only lived in the session it would reset.
        It must not."""
        from apps.core.models import AppConfig
        from django.test import Client

        config = AppConfig.get_solo()
        config.setup_locked = True
        config.setup_failed_attempts = 10
        config.save()

        fresh_client = Client()  # brand-new session, as if freshly launched
        response = fresh_client.get(reverse("accounts:first_setup"))
        self.assertContains(response, "غیرفعال شده است")

    def test_setup_password_is_never_stored_in_plaintext(self):
        from apps.accounts.models import SETUP_PASSWORD_HASH

        self.assertNotEqual(SETUP_PASSWORD_HASH, self.CORRECT)
        self.assertTrue(SETUP_PASSWORD_HASH.startswith("pbkdf2_"))

    def test_setup_password_hash_is_distinct_from_license_renewal_hash(self):
        from apps.accounts.models import SETUP_PASSWORD_HASH
        from apps.license.models import RENEWAL_PASSWORD_HASH

        self.assertNotEqual(SETUP_PASSWORD_HASH, RENEWAL_PASSWORD_HASH)

    def test_license_renewal_flow_is_unaffected(self):
        """Renewal uses a completely separate password/hash and is
        untouched by any of this."""
        self._post()  # creates the account + license
        self.client.logout()
        self.client.login(username="operator", password="StrongPass123!")

        # Wrong renewal password must not be affected by, or affect, the
        # setup-password attempt counter.
        from apps.core.models import AppConfig

        before = AppConfig.get_solo().setup_failed_attempts
        response = self.client.post(reverse("license:renew"), {"password": "wrong-renewal-password"})
        self.assertContains(response, "رمز تمدید نادرست است")
        self.assertEqual(AppConfig.get_solo().setup_failed_attempts, before)
