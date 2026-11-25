"""
Global UI branding: the Panah Studios logo on the login page and in the contact
footer (next to the contact info) on every page; the header carries no logo (shared partials -- one
logo asset, one contact text).
"""

import datetime
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Operator
from apps.license.models import License
from apps.stations.models import Station

User = get_user_model()

LOGO_URL = "/static/img/panah-studios-logo.png"
CONTACT_TEXT = "ارتباط با ما : شماره تماس : 09222380266 ایمیل : panah.studios@gmail.com"


def visible_text(html):
    """The page's text with markup stripped and whitespace normalised."""
    html = re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


class LogoAssetTests(TestCase):
    def test_logo_is_a_transparent_png_stored_once_under_static(self):
        from PIL import Image

        path = Path(settings.BASE_DIR) / "static" / "img" / "panah-studios-logo.png"
        self.assertTrue(path.is_file())
        image = Image.open(path)
        self.assertEqual(image.mode, "RGBA")
        width, height = image.size
        for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
            self.assertEqual(image.getpixel(corner)[3], 0, "the white background must be gone")
        self.assertGreater(image.getextrema()[3][1], 200)                  # the drawing itself is opaque
        # The collected copy served by the packaged app is the very same file.
        collected = Path(settings.BASE_DIR) / "staticfiles" / "img" / "panah-studios-logo.png"
        self.assertEqual(path.read_bytes(), collected.read_bytes())


class BrandingPagesTests(TestCase):
    SECTIONS = (
        "/", "/sales/invoices/", "/purchases/", "/inventory/",
        "/reports/nozzle-ledger/", "/reports/all-nozzles/", "/reports/petroleum-ledger/",
        "/reports/petroleum-monthly/", "/seals/", "/deposits/", "/statement/", "/comparison/",
    )

    def setUp(self):
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        self.station = Station.objects.create(name="Koohi 118", province="Razavi Khorasan", city="Mashhad")
        self.user = User.objects.create_user(username="op1", password="testpass123")
        operator = Operator(user=self.user, security_question="نام شهر؟")
        operator.set_security_answer("مشهد")
        operator.save()

    def login(self):
        self.client.login(username="op1", password="testpass123")

    # --- header (unchanged: no logo) -------------------------------------

    def test_header_is_the_original_one_without_a_logo(self):
        self.login()
        html = self.client.get("/").content.decode()
        header = html.split('<header class="app-header">', 1)[1].split("</header>", 1)[0]
        self.assertNotIn("<img", header)
        self.assertNotIn("panah", header.lower())
        self.assertIn('<span class="app-header__station-name">کوهی ۱۱۸</span>', header)
        self.assertIn('<span class="app-header__station-location">خراسان رضوی، مشهد</span>', header)

    def test_logo_and_footer_on_every_section(self):
        self.login()
        for url in self.SECTIONS:
            resp = self.client.get(url, follow=True)
            self.assertEqual(resp.status_code, 200, url)
            html = resp.content.decode()
            self.assertEqual(html.count(LOGO_URL), 1, url)                     # one logo, same asset everywhere
            self.assertEqual(html.count('<footer class="app-footer">'), 1, url)
            footer = html.split("<footer", 1)[1]
            self.assertIn(LOGO_URL, footer, url)                               # ... and it is in the footer, with the contact info
            self.assertIn("app-footer__logo", footer, url)
            self.assertIn(CONTACT_TEXT, visible_text(html.split("<footer", 1)[1]), url)
            # The footer comes after all page content, never inside <main>.
            self.assertGreater(html.index("<footer"), html.index("</main>"), url)

    def test_footer_text_is_exact(self):
        self.login()
        html = self.client.get("/").content.decode()
        self.assertIn('شماره تماس : <bdi dir="ltr">09222380266</bdi>', html)
        self.assertIn('ایمیل : <bdi dir="ltr">panah.studios@gmail.com</bdi>', html)
        self.assertIn("ارتباط با ما :", html)

    def test_layout_css_keeps_the_footer_below_content(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "base.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"body \{[^}]*min-height: 100vh;[^}]*flex-direction: column;")
        self.assertIn("body > main { flex: 1 0 auto; }", css)
        # Regression (seen in real Chromium): inside the column-flex <body> a centred .app-main must
        # keep its width instead of shrinking to its content, and the class-less sign-in <main> must
        # stay a column so .auth-shell still centres its card.
        self.assertIn("width: min(100%, calc(1100px + 3rem));", css)
        self.assertIn("body > main:not(.app-main) {", css)
        self.assertIn(".app-footer__logo {", css)
        self.assertNotIn(".app-header__logo", css)
        self.assertEqual(css, (Path(settings.BASE_DIR) / "staticfiles" / "css" / "base.css").read_text(encoding="utf-8"))

    # --- login page -----------------------------------------------------

    def test_login_page_order_logo_fields_forgot_contact(self):
        html = self.client.get(reverse("accounts:login")).content.decode()
        positions = [
            html.index(LOGO_URL),
            html.index('name="username"'),
            html.index('name="password"'),
            html.index(reverse("accounts:forgot_password")),
            html.index("ارتباط با ما :"),
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(html.count(LOGO_URL), 1)
        self.assertEqual(html.count("ارتباط با ما :"), 1)                      # card text only, no second footer copy
        self.assertNotIn("<footer", html)
        self.assertIn(CONTACT_TEXT, visible_text(html))
        self.assertIn("رمز خود را فراموش کردم", html)

    def test_login_logo_sits_above_the_form_not_beside_it(self):
        html = self.client.get(reverse("accounts:login")).content.decode()
        card = html.split('class="auth-card"', 1)[1]
        self.assertLess(card.index("auth-card__logo"), card.index("<form"))
        self.assertLess(card.index("auth-card__logo"), card.index("auth-card__header"))

    def test_login_still_works_and_recovery_link_still_opens(self):
        bad = self.client.post(reverse("accounts:login"), {"username": "op1", "password": "wrong"})
        self.assertEqual(bad.status_code, 200)
        good = self.client.post(reverse("accounts:login"), {"username": "op1", "password": "testpass123"})
        self.assertEqual(good.status_code, 302)
        self.client.logout()
        forgot = self.client.get(reverse("accounts:forgot_password"))
        self.assertEqual(forgot.status_code, 200)
        self.assertEqual(forgot.content.decode().count('<footer class="app-footer">'), 1)   # footer on the other auth pages
