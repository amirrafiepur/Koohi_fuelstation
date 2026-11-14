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

from .ordering import nozzle_order, tank_order

#: Product.name of the CNG product. Its nozzles are identified as
#: "CNG 1".."CNG 4", independent of the regular petrol numbering 1..14.
CNG_PRODUCT_NAME = "CNG"


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
    A fuel product/grade, e.g. Regular or CNG. Kept extensible -- product
    names must never be hardcoded into calculation logic.
    """

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"

    @property
    def has_test_field(self) -> bool:
        """Whether sales for this product record a «تست» (test) quantity.
        Regular petrol does; CNG does not -- its sales are
        previous meter, new meter and rate only."""
        return self.name != CNG_PRODUCT_NAME

    def __str__(self):
        return self.name


class TankQuerySet(models.QuerySet):
    def inventory_tracked(self):
        """
        Tanks that take part in purchase, inventory, tank-statement and
        monthly comparison accounting: every tank EXCEPT CNG. CNG has no
        purchase invoices and no tank inventory in this station's
        accounting; it exists as a Tank row only so its nozzles have a
        product. Every inventory-related screen, report and PDF must
        start from this queryset, never from Tank.objects directly.
        """
        return self.exclude(product__name=CNG_PRODUCT_NAME)


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

    objects = TankQuerySet.as_manager()

    class Meta:
        verbose_name = "Tank"
        verbose_name_plural = "Tanks"
        # Regular first, then CNG (see ordering.py).
        ordering = tank_order()

    @property
    def tracks_inventory(self) -> bool:
        """False for CNG (no purchases / tank inventory); see
        TankQuerySet.inventory_tracked()."""
        return self.product.name != CNG_PRODUCT_NAME

    def __str__(self):
        return f"{self.product.name} tank"


class NozzleQuerySet(models.QuerySet):
    def sealable(self):
        """Nozzles that carry seal numbers («پلمپ ها»): every nozzle
        except CNG -- CNG nozzles have no seals in this station."""
        return self.exclude(tank__product__name=CNG_PRODUCT_NAME)


class Nozzle(models.Model):
    """
    A dispensing nozzle attached to a tank. No active/inactive status: a
    non-operating nozzle still receives a daily zero-value record rather
    than being flagged inactive (see workday/sales business rules).

    `number` is numbered WITHIN its product, not station-wide: Regular
    nozzles are 1..14 and CNG nozzles are CNG 1..CNG 4. A CNG nozzle is
    therefore never "nozzle 15..18" -- its identity is always the pair
    (product, number), exposed as `identifier` / `label` below.
    """

    tank = models.ForeignKey(
        Tank, on_delete=models.PROTECT, related_name="nozzles"
    )
    number = models.PositiveIntegerField()

    objects = NozzleQuerySet.as_manager()

    class Meta:
        verbose_name = "Nozzle"
        verbose_name_plural = "Nozzles"
        ordering = nozzle_order()
        constraints = [
            models.UniqueConstraint(
                fields=["tank", "number"], name="unique_nozzle_number_per_tank"
            ),
        ]

    @property
    def is_cng(self) -> bool:
        return self.tank.product.name == CNG_PRODUCT_NAME

    @property
    def has_test_field(self) -> bool:
        """False for CNG nozzles: no «تست» is entered, shown or counted."""
        return self.tank.product.has_test_field

    @property
    def has_seals(self) -> bool:
        """False for CNG nozzles: they have no seal numbers («پلمپ ها»)."""
        return not self.is_cng

    @property
    def identifier(self) -> str:
        """Short identifier shown in a "نازل" column: "5" for regular
        petrol nozzle 5, "CNG 1" for CNG nozzle 1."""
        return f"CNG {self.number}" if self.is_cng else str(self.number)

    @property
    def label(self) -> str:
        """Full Persian label: «نازل 5» / «نازل CNG 1»."""
        return f"نازل {self.identifier}"

    def __str__(self):
        return f"Nozzle {self.identifier}"
