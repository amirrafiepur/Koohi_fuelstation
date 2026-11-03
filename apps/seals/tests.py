import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.license.models import License
from apps.stations.models import Station, Product, Tank, Nozzle

from .models import NozzleSeal

User = get_user_model()


class SealHttpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op1", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S", province="P", city="C")
        product = Product.objects.create(name="Regular")
        tank = Tank.objects.create(station=station, product=product, capacity=50000)
        self.nozzle = Nozzle.objects.create(tank=tank, number=1)
        self.client.login(username="op1", password="testpass123")

    def test_seal_list_renders_empty(self):
        resp = self.client.get("/seals/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "پلمپی ثبت نشده است")

    def test_create_seal(self):
        resp = self.client.post("/seals/new/", {
            "nozzle": self.nozzle.id,
            "section": NozzleSeal.FLAG_DOOR_1,
            "date": "1405/05/10",
            "seal_number": "SN-001",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(NozzleSeal.objects.count(), 1)
        seal = NozzleSeal.objects.first()
        self.assertEqual(seal.seal_number, "SN-001")

    def test_seal_is_event_based_not_daily(self):
        """Multiple seals for the same nozzle on different (or the same)
        dates are all independently stored -- no daily uniqueness."""
        self.client.post("/seals/new/", {
            "nozzle": self.nozzle.id, "section": NozzleSeal.FLAG_DOOR_1,
            "date": "1405/05/10", "seal_number": "SN-001",
        })
        self.client.post("/seals/new/", {
            "nozzle": self.nozzle.id, "section": NozzleSeal.FLAG_DOOR_1,
            "date": "1405/05/10", "seal_number": "SN-002",
        })
        self.assertEqual(NozzleSeal.objects.filter(nozzle=self.nozzle).count(), 2)

    def test_edit_seal(self):
        seal = NozzleSeal.objects.create(
            nozzle=self.nozzle, section=NozzleSeal.PUMP_DOOR_1,
            date=datetime.date(2026, 8, 1), seal_number="OLD-001",
        )
        resp = self.client.post(f"/seals/{seal.pk}/edit/", {
            "nozzle": self.nozzle.id, "section": NozzleSeal.PUMP_DOOR_1,
            "date": "1405/05/10", "seal_number": "NEW-001",
        })
        self.assertEqual(resp.status_code, 302)
        seal.refresh_from_db()
        self.assertEqual(seal.seal_number, "NEW-001")

    def test_delete_seal_requires_post_confirmation(self):
        seal = NozzleSeal.objects.create(
            nozzle=self.nozzle, section=NozzleSeal.PUMP_DOOR_1,
            date=datetime.date(2026, 8, 1), seal_number="SN-001",
        )
        # GET shows confirmation, does not delete.
        resp_get = self.client.get(f"/seals/{seal.pk}/delete/")
        self.assertEqual(resp_get.status_code, 200)
        self.assertEqual(NozzleSeal.objects.count(), 1)

        # POST actually deletes.
        resp_post = self.client.post(f"/seals/{seal.pk}/delete/")
        self.assertEqual(resp_post.status_code, 302)
        self.assertEqual(NozzleSeal.objects.count(), 0)

    def test_seal_list_shows_created_seal(self):
        NozzleSeal.objects.create(
            nozzle=self.nozzle, section=NozzleSeal.FLAG_DOOR_2,
            date=datetime.date(2026, 8, 1), seal_number="SN-777",
        )
        # Explicit range covering the seal's date -- the list now
        # defaults to only the global Date Control's date (see
        # SealDateRangeFilterTests below), which this fixture's seal
        # doesn't necessarily fall within.
        resp = self.client.get("/seals/?start_date=2026-08-01&end_date=2026-08-01")
        self.assertContains(resp, "SN-777")


class SealFormPersianizationTests(TestCase):
    """
    2.3: the نازل dropdown must show "نازل N" (not the model's internal
    "Nozzle N" __str__). 2.4: the بخش field's options must be Persian,
    while the stored values (flag_door_1 etc.) are unchanged.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="op_seal_disp", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S2", province="P", city="C")
        product = Product.objects.create(name="Regular")
        tank = Tank.objects.create(station=station, product=product, capacity=50000)
        self.nozzle = Nozzle.objects.create(tank=tank, number=5)
        self.client.login(username="op_seal_disp", password="testpass123")

    def test_nozzle_dropdown_shows_persian_label_not_english(self):
        resp = self.client.get("/seals/new/")
        content = resp.content.decode()
        self.assertIn("نازل 5", content)
        self.assertNotIn("Nozzle 5", content)

    def test_section_field_options_are_persian(self):
        resp = self.client.get("/seals/new/")
        content = resp.content.decode()
        for label in ["درب پرچمی 1", "درب پرچمی 2", "درب تلمبه 1", "درب تلمبه 2"]:
            self.assertIn(label, content)
        for old_label in ["Flag Door 1", "Flag Door 2", "Pump Door 1", "Pump Door 2"]:
            self.assertNotIn(old_label, content)

    def test_section_stored_value_unchanged_after_submit(self):
        resp = self.client.post("/seals/new/", {
            "nozzle": self.nozzle.id, "section": NozzleSeal.FLAG_DOOR_1,
            "date": "1405/06/05", "seal_number": "SEAL-1",
        })
        self.assertEqual(resp.status_code, 302)
        seal = NozzleSeal.objects.get()
        self.assertEqual(seal.section, "flag_door_1")


class SealDateRangeFilterTests(TestCase):
    """
    Task: پلمپ‌ها date-range filtering, mirroring دفتر موجودی و عملیات's
    UI/workflow. Default range = both ends equal to the global Date
    Control's current date; changing the range filters accordingly;
    a print button is present once there's something to print.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="op_range", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 8, 1), duration_days=365)
        station = Station.objects.create(name="S_range", province="P", city="C")
        product = Product.objects.create(name="Regular")
        tank = Tank.objects.create(station=station, product=product, capacity=50000)
        self.nozzle = Nozzle.objects.create(tank=tank, number=1)
        self.client.login(username="op_range", password="testpass123")

    def _set_global_date(self, date):
        resp = self.client.post("/set-date/", {
            "date": date.isoformat(), "next": "/seals/", "section": "seals",
        })
        return resp

    def test_default_range_shows_only_global_dates_seals(self):
        self._set_global_date(datetime.date(2026, 8, 5))
        NozzleSeal.objects.create(
            nozzle=self.nozzle, section=NozzleSeal.FLAG_DOOR_1,
            date=datetime.date(2026, 8, 5), seal_number="ON-GLOBAL-DATE",
        )
        NozzleSeal.objects.create(
            nozzle=self.nozzle, section=NozzleSeal.FLAG_DOOR_1,
            date=datetime.date(2026, 8, 6), seal_number="OTHER-DAY",
        )
        resp = self.client.get("/seals/")
        content = resp.content.decode()
        self.assertIn("ON-GLOBAL-DATE", content)
        self.assertNotIn("OTHER-DAY", content)

    def test_default_date_inputs_both_equal_global_date(self):
        self._set_global_date(datetime.date(2026, 8, 5))
        resp = self.client.get("/seals/")
        content = resp.content.decode()
        self.assertIn('data-nav-template="?start_date=__ISO__&end_date=2026-08-05"', content)
        self.assertIn('data-nav-template="?start_date=2026-08-05&end_date=__ISO__"', content)

    def test_changing_range_shows_correct_records(self):
        NozzleSeal.objects.create(
            nozzle=self.nozzle, section=NozzleSeal.FLAG_DOOR_1,
            date=datetime.date(2026, 8, 1), seal_number="IN-RANGE",
        )
        NozzleSeal.objects.create(
            nozzle=self.nozzle, section=NozzleSeal.FLAG_DOOR_1,
            date=datetime.date(2026, 9, 1), seal_number="OUT-OF-RANGE",
        )
        resp = self.client.get("/seals/?start_date=2026-07-01&end_date=2026-08-15")
        content = resp.content.decode()
        self.assertIn("IN-RANGE", content)
        self.assertNotIn("OUT-OF-RANGE", content)

    def test_print_button_present_only_when_there_are_results(self):
        resp_empty = self.client.get("/seals/?start_date=2026-01-01&end_date=2026-01-02")
        self.assertNotContains(resp_empty, "چاپ / PDF")

        NozzleSeal.objects.create(
            nozzle=self.nozzle, section=NozzleSeal.FLAG_DOOR_1,
            date=datetime.date(2026, 8, 1), seal_number="PRINTABLE",
        )
        resp_full = self.client.get("/seals/?start_date=2026-08-01&end_date=2026-08-01")
        self.assertContains(resp_full, "چاپ / PDF")
        self.assertIn("/print/seals/?start_date=2026-08-01&end_date=2026-08-01", resp_full.content.decode())

    def test_pdf_source_html_contains_all_displayed_records(self):
        """Renders the actual print template (the exact HTML WeasyPrint
        converts to PDF) without needing weasyprint installed."""
        from django.template.loader import render_to_string

        from apps.printing.services import build_seals_context

        NozzleSeal.objects.create(
            nozzle=self.nozzle, section=NozzleSeal.FLAG_DOOR_1,
            date=datetime.date(2026, 8, 1), seal_number="PDF-1",
        )
        NozzleSeal.objects.create(
            nozzle=self.nozzle, section=NozzleSeal.FLAG_DOOR_2,
            date=datetime.date(2026, 8, 2), seal_number="PDF-2",
        )
        context = build_seals_context(datetime.date(2026, 8, 1), datetime.date(2026, 8, 2))
        html = render_to_string("printing/seals_print.html", context)
        self.assertIn("PDF-1", html)
        self.assertIn("PDF-2", html)

    def test_unrelated_seal_crud_still_works(self):
        """Scoping check: add/edit/delete are untouched by this change."""
        resp = self.client.post("/seals/new/", {
            "nozzle": self.nozzle.id, "section": NozzleSeal.FLAG_DOOR_1,
            "date": "1405/06/05", "seal_number": "STILL-WORKS",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(NozzleSeal.objects.filter(seal_number="STILL-WORKS").exists())
