"""
"صورت وضعیت ماهانه" (Monthly Statement).

Almost everything on this page is derived, read-only data reused verbatim
from apps.reports.services.petroleum_inventory_monthly() and other existing
services (see apps/statement/services.py) -- this app stores nothing that
already exists elsewhere.

The only two values this new section itself owns, because nothing existing
in the project tracks them, are per tank per (Jalali) year/month:

- digital_sales ("فروش دیجیتال"): manually entered by the operator via the
  "ورود فروش دیجیتال" button. Optional/blank until entered.
- tanker_capacity ("ظرفیت نفتکش"): manually editable, defaults to 32000 for
  a month that hasn't been edited yet. Deliberately independent from
  apps.purchases.models.PurchaseInvoice.tanker_capacity (a different,
  pre-existing per-invoice field) and from تعداد نفتکش (a derived count,
  never stored) -- kept as its own field per the task's explicit
  instruction not to conflate the two.
"""

from django.db import models

from apps.stations.models import Tank


class StatementEntry(models.Model):
    tank = models.ForeignKey(
        Tank, on_delete=models.CASCADE, related_name="statement_entries"
    )
    year = models.PositiveIntegerField(help_text="Jalali year, e.g. 1405.")
    month = models.PositiveSmallIntegerField(help_text="Jalali month, 1-12.")

    digital_sales = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text="فروش دیجیتال -- entered manually via ورود فروش دیجیتال.",
    )
    tanker_capacity = models.PositiveIntegerField(
        default=32000,
        help_text="ظرفیت نفتکش (liters). Manually editable; independent of "
                   "PurchaseInvoice.tanker_capacity and of تعداد نفتکش.",
    )

    class Meta:
        verbose_name = "Statement Entry"
        verbose_name_plural = "Statement Entries"
        unique_together = [("tank", "year", "month")]

    def __str__(self):
        return f"{self.tank} — {self.year}/{self.month}"
