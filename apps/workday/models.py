"""
DailyWorkingDay is the chronology gatekeeper: every other daily record
(sales, purchases, inventory) hangs off a DailyWorkingDay via its date.

Chronology rules (enforced in workday/services.py, not here):
  - No future date may ever be created.
  - Earlier required days must be completed before a later day can be
    finalized.
  - The required accounting sequence for the FIRST calendar month starts
    on day 1 of that month, not on the license activation date (see the
    architecture doc's "Accounting month start vs. license activation"
    rule) -- so "missing days" can include dates before the software was
    actually installed, within that first month only.
"""

from django.db import models


class DailyWorkingDay(models.Model):
    INCOMPLETE = "incomplete"
    COMPLETE = "complete"
    STATUS_CHOICES = [
        (INCOMPLETE, "Incomplete"),
        (COMPLETE, "Complete"),
    ]

    date = models.DateField(unique=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=INCOMPLETE
    )

    class Meta:
        verbose_name = "Daily Working Day"
        verbose_name_plural = "Daily Working Days"
        ordering = ["date"]

    def __str__(self):
        return f"{self.date} ({self.status})"
