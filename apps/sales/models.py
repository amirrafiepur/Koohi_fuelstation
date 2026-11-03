"""
One SalesInvoice (daily header/summary) per DailyWorkingDay, with each
nozzle's data stored separately as a NozzleSale row. Daily/product totals
are always derived from NozzleSale records via sales/services.py -- never
stored as duplicate columns (see architecture doc, "Derived vs. Stored
Data").

sales_rate is frozen on each NozzleSale at entry time: changing today's
suggested rate must never alter historical records.
"""

from django.conf import settings
from django.db import models

from apps.workday.models import DailyWorkingDay
from apps.stations.models import Nozzle


class SalesInvoice(models.Model):
    """The one-per-day sales header. Aggregated totals are derived, not
    stored -- see sales/services.py:get_daily_totals()."""

    working_day = models.OneToOneField(
        DailyWorkingDay, on_delete=models.CASCADE, related_name="sales_invoice"
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sales_invoices"
    )
    # System-generated, unique, auto-incremented internal identifier --
    # distinct from any business-entered document number (there is none
    # for sales invoices; purchase invoices are the ones with a manually
    # entered business number -- see purchases/models.py).
    invoice_number = models.AutoField(primary_key=True)
    # Informational only -- never used for chronology or calculations.
    entry_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sales Invoice"
        verbose_name_plural = "Sales Invoices"

    def __str__(self):
        return f"Sales invoice #{self.invoice_number} ({self.working_day.date})"


class NozzleSale(models.Model):
    """
    One record per nozzle per working day. A non-operating nozzle still
    gets a row here with previous_meter == new_meter and test == 0 (see
    sales/services.py for the calculation helpers and the non-operating
    entry path).
    """

    sales_invoice = models.ForeignKey(
        SalesInvoice, on_delete=models.CASCADE, related_name="nozzle_sales"
    )
    nozzle = models.ForeignKey(
        Nozzle, on_delete=models.PROTECT, related_name="sales"
    )
    previous_meter = models.DecimalField(max_digits=14, decimal_places=2)
    new_meter = models.DecimalField(max_digits=14, decimal_places=2)
    test = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # Frozen at entry time -- see module docstring.
    sales_rate = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        verbose_name = "Nozzle Sale"
        verbose_name_plural = "Nozzle Sales"
        constraints = [
            models.UniqueConstraint(
                fields=["nozzle", "sales_invoice"],
                name="unique_nozzle_per_sales_invoice",
            )
        ]

    def __str__(self):
        return f"Nozzle {self.nozzle.number} — {self.sales_invoice.working_day.date}"

    # --- Derived values -----------------------------------------------
    # Exposed as simple properties per the architecture's "models may
    # expose simple derived properties" allowance. Multi-record
    # aggregations (product sales, daily totals) live in services.py,
    # not here.

    @property
    def operation(self):
        """Operation = New Meter - Previous Meter."""
        return self.new_meter - self.previous_meter

    @property
    def mechanical_sales(self):
        """Mechanical Sales = Operation - Test."""
        return self.operation - self.test

    @property
    def sales_amount(self):
        """Sales = Mechanical Sales."""
        return self.mechanical_sales

    @property
    def total_amount(self):
        """Total Amount = Mechanical Sales x Sales Rate."""
        return self.mechanical_sales * self.sales_rate
