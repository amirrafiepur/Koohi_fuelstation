"""
Multiple PurchaseInvoice records may exist per working day per tank/product.
Business-entered identifiers (document number, tanker number) intentionally
carry NO uniqueness constraint -- the operator owns their correctness (see
architecture doc, "Purchase Identifiers").
"""

from django.db import models

from apps.workday.models import DailyWorkingDay
from apps.stations.models import Tank


class PurchaseInvoice(models.Model):
    working_day = models.ForeignKey(
        DailyWorkingDay, on_delete=models.CASCADE, related_name="purchase_invoices"
    )
    tank = models.ForeignKey(
        Tank, on_delete=models.PROTECT, related_name="purchase_invoices"
    )

    # Informational fields (§ purchase entry form in the architecture doc).
    unloading_time = models.TimeField(null=True, blank=True)
    program_number = models.CharField(max_length=100, blank=True)
    tanker_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Vehicle/license plate. No uniqueness constraint -- "
                   "operator-owned business identifier.",
    )
    tanker_capacity = models.PositiveIntegerField(
        null=True, blank=True, help_text="Liters. No fixed restriction enforced."
    )

    quantity = models.PositiveIntegerField(help_text="Liters (integer quantities only).")
    purchase_rate = models.DecimalField(max_digits=14, decimal_places=2)

    # Business-entered document/invoice number -- deliberately NOT unique.
    document_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Manually entered by the operator. No uniqueness or "
                   "duplicate validation is applied; the operator is "
                   "responsible for correctness.",
    )

    class Meta:
        verbose_name = "Purchase Invoice"
        verbose_name_plural = "Purchase Invoices"

    def __str__(self):
        return f"Purchase — {self.tank.product.name} — {self.working_day.date} ({self.quantity} L)"

    @property
    def total_amount(self):
        return self.quantity * self.purchase_rate
