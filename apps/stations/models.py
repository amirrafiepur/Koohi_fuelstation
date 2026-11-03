"""
Station configuration: the physical station, its fuel products, tanks, and
nozzles.

Per the architecture spec, nozzle-to-tank-to-product relationships live
entirely in the database -- never hardcoded into business logic elsewhere.
There is no active/inactive field on Nozzle, and no add/remove-nozzle UI is
built in Phase 1; future nozzle changes are made directly via the database
or Django admin.
"""

from django.db import models


class Station(models.Model):
    """Represents the physical station. Effectively a singleton row."""

    name = models.CharField(max_length=255)
    province = models.CharField(max_length=255)
    city = models.CharField(max_length=255)

    class Meta:
        verbose_name = "Station"
        verbose_name_plural = "Stations"

    def __str__(self):
        return self.name


class Product(models.Model):
    """
    A fuel product/grade, e.g. Regular or Super. Kept extensible -- product
    names must never be hardcoded into calculation logic.
    """

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"

    def __str__(self):
        return self.name


class Tank(models.Model):
    """A physical storage tank holding one product at the station."""

    station = models.ForeignKey(
        Station, on_delete=models.PROTECT, related_name="tanks"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="tanks"
    )
    capacity = models.PositiveIntegerField(
        help_text="Tank capacity in liters."
    )

    class Meta:
        verbose_name = "Tank"
        verbose_name_plural = "Tanks"

    def __str__(self):
        return f"{self.product.name} tank"


class Nozzle(models.Model):
    """
    A dispensing nozzle attached to a tank. No active/inactive status: a
    non-operating nozzle still receives a daily zero-value record rather
    than being flagged inactive (see workday/sales business rules).
    """

    tank = models.ForeignKey(
        Tank, on_delete=models.PROTECT, related_name="nozzles"
    )
    number = models.PositiveIntegerField(unique=True)

    class Meta:
        verbose_name = "Nozzle"
        verbose_name_plural = "Nozzles"
        ordering = ["number"]

    def __str__(self):
        return f"Nozzle {self.number}"
