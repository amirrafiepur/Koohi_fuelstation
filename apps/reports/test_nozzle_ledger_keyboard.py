"""
Keyboard navigation on "گزارش کارکرد هر نازل" -- two modes toggled by Enter.

Two layers:
  * structural checks on the rendered page (always run);
  * real behaviour tests: the page's actual inline script is executed in
    jsdom (Node) and driven with KeyboardEvents by js_tests/
    nozzle_ledger_keyboard.js. These skip themselves when Node or the
    `jsdom` package is not installed (this project has no JS toolchain of
    its own); to run them: `npm install jsdom` somewhere and point
    JSDOM_NODE_PATH at its node_modules folder (or set NODE_PATH).
"""

import datetime
import json
import os
import shutil
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.license.models import License
from apps.sales.models import NozzleSale, SalesInvoice
from apps.stations.models import Nozzle, Product, Station, Tank
from apps.workday.models import DailyWorkingDay

User = get_user_model()
HARNESS = Path(__file__).parent / "js_tests" / "nozzle_ledger_keyboard.js"
DAYS = 45


def _node_with_jsdom():
    node = shutil.which("node")
    if not node:
        return None, {}
    env = dict(os.environ)
    paths = [p for p in (os.environ.get("JSDOM_NODE_PATH"), os.environ.get("NODE_PATH")) if p]
    if paths:
        env["NODE_PATH"] = os.pathsep.join(paths)
    probe = subprocess.run([node, "-e", "require('jsdom')"], env=env, capture_output=True)
    return (node, env) if probe.returncode == 0 else (None, {})


NODE, NODE_ENV = _node_with_jsdom()


class NozzleLedgerKeyboardBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="op_kb", password="testpass123")
        License.objects.create(start_date=datetime.date(2026, 7, 23), duration_days=365)
        station = Station.objects.create(name="S", province="P", city="C")
        tank = Tank.objects.create(station=station, product=Product.objects.create(name="Regular"), capacity=50000)
        self.nozzles = {n: Nozzle.objects.create(tank=tank, number=n) for n in range(1, 27)}
        self.client.login(username="op_kb", password="testpass123")
        meter = Decimal("0")
        for i in range(DAYS):
            wd = DailyWorkingDay.objects.create(date=datetime.date(2026, 7, 23) + datetime.timedelta(days=i))
            invoice = SalesInvoice.objects.create(working_day=wd, operator=self.user)
            NozzleSale.objects.create(
                sales_invoice=invoice, nozzle=self.nozzles[10], previous_meter=meter,
                new_meter=meter + 100, test=Decimal("2"), sales_rate=Decimal("1200"),
            )
            meter += 100

    def page(self, nozzle_number, start="2026-07-23", end="2026-09-30"):
        resp = self.client.get(
            f"/reports/nozzle-ledger/?nozzle_id={self.nozzles[nozzle_number].id}&start_date={start}&end_date={end}"
        )
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()


class NozzleLedgerKeyboardStructureTests(NozzleLedgerKeyboardBase):
    def test_page_has_the_hooks_the_script_needs(self):
        html = self.page(10)
        self.assertIn('id="nozzle-ledger-table"', html)
        self.assertIn('id="table-mode-hint"', html)
        self.assertIn("row-selected", html)
        self.assertIn("'Enter'", html)
        self.assertIn("scrollIntoView", html)
        self.assertEqual(html.count("<tbody>"), 1)
        self.assertEqual(html.count("<tr ") - 1, DAYS)   # header row + one per day

    def test_selected_row_style_is_blue(self):
        self.assertRegex(self.page(10), r"tr\.row-selected td \{[^}]*background: #1d4ed8")

    def test_original_nozzle_shortcuts_are_still_wired(self):
        html = self.page(10)
        for needle in ("ArrowUp", "ArrowDown", "keydown", "nozzle-select", "'input'", "'select'",
                       "isContentEditable", "Math.min(currentIndex + 1", "Math.max(currentIndex - 1"):
            self.assertIn(needle, html)

    def test_report_data_and_filters_are_unchanged(self):
        html = self.page(10, "2026-07-23", "2026-07-25")
        self.assertEqual(html.count("<tr ") - 1, 3)
        self.assertIn("start_date=2026-07-23", html)
        self.assertIn("end_date=2026-07-25", html)


import unittest  # noqa: E402


@unittest.skipUnless(NODE, "Node.js with the jsdom package is not installed (optional dev-only check)")
class NozzleLedgerKeyboardBehaviourTests(NozzleLedgerKeyboardBase):
    """Runs the page's real script in jsdom -- see js_tests/nozzle_ledger_keyboard.js."""

    def test_keyboard_modes_behave_as_specified(self):
        with tempfile.TemporaryDirectory() as tmp:
            full = Path(tmp) / "full.html"
            empty = Path(tmp) / "empty.html"
            full.write_text(self.page(10), encoding="utf-8")
            empty.write_text(self.page(11), encoding="utf-8")      # nozzle 11 has no sales
            result = subprocess.run(
                [NODE, str(HARNESS), str(full), str(empty)],
                env=NODE_ENV, capture_output=True, text=True, timeout=120,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        checks = json.loads(result.stdout)
        self.assertGreaterEqual(len(checks), 35)
        failed = [name for name, ok in checks.items() if not ok]
        self.assertEqual(failed, [], f"failed browser-behaviour checks: {failed}")
