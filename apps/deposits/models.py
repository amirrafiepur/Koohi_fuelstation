"""
Deposits are fully optional: no record is required when there is no
deposit activity for a given period. Decade boundaries (1st = 1-10,
2nd = 11-20, 3rd = 21-end of month) are computed in reports/services.py,
not stored, so they automatically handle 28/29/30/31-day months correctly.
"""

from django.db import models


class Deposit(models.Model):
    FIRST_DECADE = "first"
    SECOND_DECADE = "second"
    THIRD_DECADE = "third"
    DECADE_CHOICES = [
        (FIRST_DECADE, "دهه اول"),
        (SECOND_DECADE, "دهه دوم"),
        (THIRD_DECADE, "دهه سوم"),
    ]

    date = models.DateField(
        help_text="Defaults to system date at entry time; may be adjusted "
                   "for a valid historical entry. Never overwritten on edit."
    )
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()
    decade = models.CharField(max_length=10, choices=DECADE_CHOICES)

    difference_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    deposit_amount = models.DecimalField(max_digits=14, decimal_places=2)
    document_number = models.CharField(max_length=100, blank=True)
    bank = models.CharField(max_length=100, blank=True)
    branch = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = "Deposit"
        verbose_name_plural = "Deposits"
        ordering = ["-date"]

    def __str__(self):
        return f"Deposit — {self.date} — {self.deposit_amount}"
