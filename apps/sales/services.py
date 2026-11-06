"""
sales/services.py -- sales-side business logic. Formulas here mirror the
properties on NozzleSale (see sales/models.py) but this module is where
multi-record aggregation (product sales, daily totals, completion checks)
belongs.
"""

from decimal import Decimal

from .models import SalesInvoice, NozzleSale
from apps.stations.models import Nozzle, Tank


def get_or_create_sales_invoice(working_day, operator):
    invoice, _ = SalesInvoice.objects.get_or_create(
        working_day=working_day, defaults={"operator": operator}
    )
    return invoice


def create_nozzle_sale(sales_invoice, nozzle, previous_meter, new_meter, test, sales_rate):
    """
    Creates a NozzleSale row. Does not itself decide whether New Meter <
    Previous Meter should warn -- that non-blocking warning is a form/view
    concern (the user must be able to confirm and save regardless).
    """
    return NozzleSale.objects.create(
        sales_invoice=sales_invoice,
        nozzle=nozzle,
        previous_meter=previous_meter,
        new_meter=new_meter,
        test=test,
        sales_rate=sales_rate,
    )


def get_product_sales(tank: Tank, working_day) -> Decimal:
    """Product Sales = sum of Mechanical Sales for all nozzles of this
    tank/product on this working day."""
    qs = NozzleSale.objects.filter(
        nozzle__tank=tank, sales_invoice__working_day=working_day
    )
    return sum((sale.mechanical_sales for sale in qs), Decimal("0"))


def get_daily_totals(working_day) -> dict:
    """Aggregate totals for the daily SalesInvoice view: total operation,
    total tests, total sales, total amount -- all derived from NozzleSale
    rows, never stored."""
    try:
        invoice = SalesInvoice.objects.get(working_day=working_day)
    except SalesInvoice.DoesNotExist:
        return {
            "nozzle_count": 0,
            "total_operation": Decimal("0"),
            "total_test": Decimal("0"),
            "total_sales": Decimal("0"),
            "total_amount": Decimal("0"),
        }

    sales = list(invoice.nozzle_sales.all())
    return {
        "nozzle_count": len(sales),
        "total_operation": sum((s.operation for s in sales), Decimal("0")),
        "total_test": sum((s.test for s in sales), Decimal("0")),
        "total_sales": sum((s.mechanical_sales for s in sales), Decimal("0")),
        "total_amount": sum((s.total_amount for s in sales), Decimal("0")),
    }


def get_most_recent_rate(tank) -> Decimal | None:
    """The most recently used sales rate for this tank's product, to
    suggest as the default for the next entry. Regular and CNG are
    always independent since this is filtered by tank (and therefore by
    product)."""
    last_sale = (
        NozzleSale.objects.filter(nozzle__tank=tank)
        .order_by("-sales_invoice__working_day__date", "-id")
        .first()
    )
    return last_sale.sales_rate if last_sale else None


def get_previous_new_meter(nozzle: Nozzle) -> Decimal | None:
    """
    The New Meter from this nozzle's most recent prior NozzleSale, to
    suggest as the default Previous Meter for the next entry -- exactly
    the same pattern as get_most_recent_rate() above, just per-nozzle
    instead of per-tank (each nozzle's meter is independent even within
    the same tank/product). Previous Meter is hand-entered only on this
    nozzle's very first entry ever (when this returns None); every entry
    after that is pre-filled from this, but -- like the suggested sales
    rate -- remains a normal, freely editable field, never locked or
    made read-only.
    """
    last_sale = (
        NozzleSale.objects.filter(nozzle=nozzle)
        .order_by("-sales_invoice__working_day__date", "-id")
        .first()
    )
    return last_sale.new_meter if last_sale else None


def validate_all_nozzles_registered(working_day) -> tuple[bool, list[Nozzle]]:
    """
    Returns (all_registered, missing_nozzles) -- the latter as Nozzle
    objects in the فاکتورهای فروش entry sequence: regular petrol nozzles
    1..14, then CNG 1..CNG 4 (the Nozzle model's own ordering, see
    stations/ordering.py). A working day cannot be marked complete (see
    workday/services.py:close_day) until every Nozzle has a NozzleSale
    row for it.
    """
    all_nozzles = list(Nozzle.objects.select_related("tank__product"))

    try:
        invoice = SalesInvoice.objects.get(working_day=working_day)
        registered_ids = set(invoice.nozzle_sales.values_list("nozzle_id", flat=True))
    except SalesInvoice.DoesNotExist:
        registered_ids = set()

    missing = [n for n in all_nozzles if n.pk not in registered_ids]
    return (len(missing) == 0, missing)


def get_daily_sales(tank: Tank, working_day) -> Decimal:
    """
    Daily sales (Mechanical Sales) for a tank/working day, summed across
    all nozzles of that tank. This is the same as Product Sales, since
    each tank has exactly one product.
    """
    return get_product_sales(tank, working_day)
