"""
TankInventory holds the one manually-entered field per tank per day
(actual_inventory); everything else (Total/Theoretical Inventory,
Shortage, Overage) is derived -- see inventory/services.py, which is also
where the previous-day carry-forward chain (Previous Balance, Previous
Overage) is resolved, deliberately avoiding the same-day circularity the
architecture doc calls out.

OpeningInventory exists only to seed day 1 of the FIRST accounting month
(the calendar month containing the license activation date -- not the
activation date itself). It is never consulted for any later month; from
month two onward the chain always continues from the previous month's
final Actual Inventory.
"""

from django.db import models

from apps.workday.models import DailyWorkingDay
from apps.stations.models import Tank


class TankInventory(models.Model):
    working_day = models.ForeignKey(
        DailyWorkingDay, on_delete=models.CASCADE, related_name="tank_inventories"
    )
    tank = models.ForeignKey(
        Tank, on_delete=models.PROTECT, related_name="inventories"
    )
    # The only manually entered field here -- required every working day.
    actual_inventory = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        verbose_name = "Tank Inventory"
        verbose_name_plural = "Tank Inventories"
        constraints = [
            models.UniqueConstraint(
                fields=["tank", "working_day"],
                name="unique_tank_inventory_per_day",
            )
        ]

    def __str__(self):
        return f"{self.tank.product.name} inventory — {self.working_day.date}"


class OpeningInventory(models.Model):
    """
    User-supplied (or default-0) starting balance for day 1 of the first
    accounting month, per tank. See inventory/services.py:
    compute_tank_inventory() for how this feeds Previous Balance on that
    first day only.
    """

    tank = models.ForeignKey(
        Tank, on_delete=models.PROTECT, related_name="opening_inventories"
    )
    opening_quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # First day of the relevant calendar month, e.g. 2026-08-01.
    effective_month = models.DateField(
        help_text="Day 1 of the first accounting month this opening balance applies to."
    )

    class Meta:
        verbose_name = "Opening Inventory"
        verbose_name_plural = "Opening Inventories"
        constraints = [
            models.UniqueConstraint(
                fields=["tank", "effective_month"],
                name="unique_opening_inventory_per_tank_month",
            )
        ]

    def __str__(self):
        return f"Opening inventory — {self.tank.product.name} — {self.effective_month}"
