"""
پلمپ‌ها ordering, identical on screen and in the PDF:
  1. by nozzle number ascending (1 .. 26);
  2. within a nozzle: newest first (date descending, then registration order descending).
"""

import datetime
import re

import jdatetime
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.test_number_display import pdf_text, render_pdf_with_html
from apps.license.models import License
from apps.seals import services as seal_services
from apps.seals.models import NozzleSeal
from apps.stations.models import Nozzle, Product, Station, Tank

User = get_user_model()
RANGE = "start_date=2026-07-01&end_date=2026-09-30"


def d(day):                                  # a date in Aug 2026 (Jalali 1405/05..06)
    return datetime.date(2026, 8, day)


def table_rows(html):
    body = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        rows.append(cells)
    return rows


class SealOrderingBase(TestCase):
    def setUp(self):
        User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S", province="P", city="C")
        tank = Tank.objects.create(station=station, product=Product.objects.create(name="Regular"), capacity=50000)
        self.nozzles = {n: Nozzle.objects.create(tank=tank, number=n) for n in range(1, 27)}
        self.client.login(username="op1", password="testpass123")
        for number, day, label in (
            (14, 5, "14a"), (1, 1, "1a"), (26, 3, "26a"), (2, 2, "2a"),
            (1, 4, "1b"), (10, 1, "10a"), (2, 2, "2b"),           # 2b: same date as 2a, registered later
        ):
            self.add(number, day, label)

    def add(self, number, day, label):
        return NozzleSeal.objects.create(nozzle=self.nozzles[number], section="flag_door_1", date=d(day), seal_number=label)

    def screen_order(self):
        resp = self.client.get(f"/seals/?{RANGE}")
        self.assertEqual(resp.status_code, 200)
        return [(r[1], r[4]) for r in table_rows(resp.content.decode())]        # (nozzle, seal number)

    def pdf_order(self):
        resp, html = render_pdf_with_html(self.client, f"/print/seals/?{RANGE}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b"%PDF"))
        return [(r[1], r[4]) for r in table_rows(html)]

    def labels(self, order):
        return [label for _, label in order]


class OrderingTests(SealOrderingBase):
    def test_nozzles_ascending_then_newest_first(self):
        self.assertEqual(self.labels(self.screen_order()), ["1b", "1a", "2b", "2a", "10a", "14a", "26a"])

    def test_numeric_not_text_order_of_nozzle_numbers(self):
        nozzles = [int(n) for n, _ in self.screen_order()]
        self.assertEqual(nozzles, sorted(nozzles))
        self.assertLess(nozzles.index(2), nozzles.index(10))                    # 2 before 10, not "10" before "2"

    def test_pdf_has_exactly_the_same_order_as_the_screen(self):
        self.assertEqual(self.pdf_order(), self.screen_order())

    def test_new_seal_for_a_late_nozzle_does_not_jump_ahead(self):
        self.add(14, 20, "14b")                     # newest of all, but nozzle 14
        order = self.labels(self.screen_order())
        self.assertEqual(order, ["1b", "1a", "2b", "2a", "10a", "14b", "14a", "26a"])
        self.assertEqual(order[:5], ["1b", "1a", "2b", "2a", "10a"])            # nozzles 1-13 untouched
        self.assertEqual(self.labels(self.pdf_order()), order)

    def test_new_seal_for_nozzle_1_goes_to_the_top_of_its_group(self):
        self.add(1, 10, "1c")
        order = self.labels(self.screen_order())
        self.assertEqual(order[:3], ["1c", "1b", "1a"])
        self.assertEqual(order, ["1c", "1b", "1a", "2b", "2a", "10a", "14a", "26a"])
        self.assertEqual(self.labels(self.pdf_order()), order)

    def test_same_date_newest_registration_first(self):
        self.add(1, 4, "1b2")                       # same date as 1b, registered after it
        self.assertEqual(self.labels(self.screen_order())[:3], ["1b2", "1b", "1a"])

    def test_an_older_dated_seal_registered_later_sits_below_newer_dates(self):
        self.add(1, 1, "1z")                        # registered last, but dated like 1a: after 1b by date, before 1a by registration
        self.assertEqual(self.labels(self.screen_order())[:3], ["1b", "1z", "1a"])
        NozzleSeal.objects.create(nozzle=self.nozzles[1], section="pump_door_1", date=datetime.date(2026, 7, 15), seal_number="1old")
        self.assertEqual(self.labels(self.screen_order())[:4], ["1b", "1z", "1a", "1old"])

    def test_inserting_for_many_nozzles_keeps_the_grouping(self):
        for number in (26, 3, 14, 1, 20, 7, 14, 1):
            self.add(number, 12, f"x{number}-{NozzleSeal.objects.count()}")
        nozzles = [int(n) for n, _ in self.screen_order()]
        self.assertEqual(nozzles, sorted(nozzles))
        self.assertEqual(self.pdf_order(), self.screen_order())

    def test_the_real_registration_form_places_new_seals_correctly(self):
        """Register through the actual form, as the operator does."""
        def register(number, gregorian):
            jalali = jdatetime.date.fromgregorian(date=gregorian).strftime("%Y/%m/%d")
            resp = self.client.post(reverse("seals:seal_create"), {
                "nozzle": self.nozzles[number].id, "section": "pump_door_2", "date": jalali, "seal_number": f"new{number}"})
            self.assertEqual(resp.status_code, 302, resp.content.decode()[:300])
        register(14, datetime.date(2026, 8, 25))
        register(1, datetime.date(2026, 8, 26))
        order = self.labels(self.screen_order())
        self.assertEqual(order, ["new1", "1b", "1a", "2b", "2a", "10a", "new14", "14a", "26a"])
        self.assertEqual(self.labels(self.pdf_order()), order)


class PreservationTests(SealOrderingBase):
    def test_all_records_and_their_data_are_preserved(self):
        before = list(NozzleSeal.objects.values_list("id", "nozzle_id", "section", "date", "seal_number").order_by("id"))
        screen, pdf = self.screen_order(), self.pdf_order()
        self.assertEqual(len(screen), len(pdf))
        self.assertEqual(len(screen), NozzleSeal.objects.count())
        self.assertEqual(sorted(self.labels(screen)), sorted(s.seal_number for s in NozzleSeal.objects.all()))
        self.assertEqual(before, list(NozzleSeal.objects.values_list("id", "nozzle_id", "section", "date", "seal_number").order_by("id")))

    def test_date_range_filter_still_applies_and_shared_query_matches_both_views(self):
        self.add(5, 28, "late")
        narrow = seal_services.seals_in_range(d(1), d(3))
        self.assertEqual([s.seal_number for s in narrow], ["1a", "2b", "2a", "10a", "26a"])      # nozzle order, newest first
        self.assertTrue(all(d(1) <= s.date <= d(3) for s in narrow))
        resp = self.client.get("/seals/?start_date=2026-08-01&end_date=2026-08-03")
        self.assertEqual([r[4] for r in table_rows(resp.content.decode())], [s.seal_number for s in narrow])
        _, html = render_pdf_with_html(self.client, "/print/seals/?start_date=2026-08-01&end_date=2026-08-03")
        self.assertEqual([r[4] for r in table_rows(html)], [s.seal_number for s in narrow])

    def test_columns_headings_and_edit_delete_links_unchanged(self):
        html = self.client.get(f"/seals/?{RANGE}").content.decode()
        for needle in ("تاریخ", "نازل", "محصول", "بخش", "شماره پلمپ", "ویرایش", "حذف"):
            self.assertIn(needle, html)
        self.assertIn("پلمپ", pdf_text(self.client.get(f"/print/seals/?{RANGE}").content))
