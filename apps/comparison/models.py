"""
"مقایسه سیستم مکانیکی و دیجیتال" (Mechanical vs Digital Comparison).

This app owns exactly one thing: the manually entered "فروش دیجیتال"
table. Its upper "فروش مکانیکی" table has no model of its own here --
it is the existing, system-generated صورت وضعیت ماهانه data, reused
verbatim via apps.statement.services.build_statement_rows() (see
apps/comparison/services.py).

DigitalEntry is deliberately a separate model/table from
apps.statement.models.StatementEntry and from every mechanical/system
source (NozzleSale, PurchaseInvoice, TankInventory, ...): the values
here are whatever the operator types in -- every column, including both
totals -- not derived from those models, not calculated, and not fed back
into them.
"""

from decimal import Decimal

from django.db import models

from apps.stations.models import Tank


class DigitalEntry(models.Model):
    tank = models.ForeignKey(
        Tank, on_delete=models.CASCADE, related_name="digital_comparison_entries"
    )
    year = models.PositiveIntegerField(help_text="Jalali year, e.g. 1405.")
    month = models.PositiveSmallIntegerField(help_text="Jalali month, 1-12.")

    # Manually entered values -- one field per input column of the
    # رسیده/خارج شده table. "آزمایش" is a single stored value, reused in
    # both the رسیده-side and خارج‌شده-side آزمایش columns, mirroring how
    # the mechanical table reuses its own single total_test_return value
    # in both places.
    beginning_inventory = models.DecimalField(
        "موجودی اول ماه", max_digits=14, decimal_places=2, default=Decimal("0"),
    )
    received_quantity = models.DecimalField(
        "مقدار رسیده", max_digits=14, decimal_places=2, default=Decimal("0"),
    )
    test_return = models.DecimalField(
        "آزمایش", max_digits=14, decimal_places=2, default=Decimal("0"),
    )
    overage = models.DecimalField(
        "سرک", max_digits=14, decimal_places=2, default=Decimal("0"),
    )
    sales_quantity = models.DecimalField(
        "مقدار فروش", max_digits=14, decimal_places=2, default=Decimal("0"),
    )
    shortage = models.DecimalField(
        "کسری", max_digits=14, decimal_places=2, default=Decimal("0"),
    )
    ending_inventory = models.DecimalField(
        "موجودی آخر ماه", max_digits=14, decimal_places=2, default=Decimal("0"),
    )

    # The two totals and the second آزمایش column are typed in by the user like
    # every other column of this table -- nothing in فروش دیجیتال is calculated.
    received_total = models.DecimalField(
        "جمع کل", max_digits=14, decimal_places=2, default=Decimal("0"),
    )
    dispatched_test_return = models.DecimalField(
        "آزمایش", max_digits=14, decimal_places=2, default=Decimal("0"),
        help_text="The آزمایش column of the خارج شده side.",
    )
    dispatched_total = models.DecimalField(
        "جمع کل خارج شده", max_digits=14, decimal_places=2, default=Decimal("0"),
    )

    class Meta:
        verbose_name = "Digital Sales Entry"
        verbose_name_plural = "Digital Sales Entries"
        unique_together = [("tank", "year", "month")]

    def __str__(self):
        return f"{self.tank} — {self.year}/{self.month} (digital)"

