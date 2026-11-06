"""
Display/entry ordering for products, tanks and nozzles.

Regular petrol always comes first, then CNG. Alphabetical product-name
ordering can't give that ("CNG" < "Regular"), so the rank is expressed
here once and reused by every query that lists tanks, nozzles, sales or
seals. A product not listed (a future third product) sorts after the
known ones, by name, so this never breaks for products added later.
"""

from django.db.models import Case, IntegerField, Value, When

#: Product.name values in the order they are shown and entered.
PRODUCT_DISPLAY_ORDER = ("Regular", "CNG")


def product_rank(product_path: str = "product"):
    """Order-by expression ranking the Product reached through
    `product_path` (e.g. "product", "tank__product",
    "nozzle__tank__product") by PRODUCT_DISPLAY_ORDER."""
    whens = [
        When(**{f"{product_path}__name": name}, then=Value(rank))
        for rank, name in enumerate(PRODUCT_DISPLAY_ORDER)
    ]
    return Case(
        *whens,
        default=Value(len(PRODUCT_DISPLAY_ORDER)),
        output_field=IntegerField(),
    )


def tank_order():
    """Tanks: Regular, then CNG."""
    return [product_rank("product"), "product__name"]


def nozzle_order(nozzle_path: str = ""):
    """Nozzles: all Regular nozzles by number (1-14), then CNG by number
    (CNG 1-4). `nozzle_path` is the lookup prefix from the queried model
    to the Nozzle ("" for Nozzle itself, "nozzle__" for NozzleSale /
    NozzleSeal)."""
    return [
        product_rank(f"{nozzle_path}tank__product"),
        f"{nozzle_path}number",
    ]
