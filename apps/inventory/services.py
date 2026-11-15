"""
inventory/services.py -- tank inventory calculations.

Carry-forward rule: a day's Total Inventory starts from the PREVIOUS
working day's ACTUAL inventory (the physically measured quantity), plus
this day's purchases and test return -- nothing else. A day's Overage
(سرک) or Shortage (کسری) is a result of that day only and never feeds
into any other day's Total Inventory, Theoretical Inventory, Shortage or
Dispatched totals: the previous day's actual inventory already includes
whatever it physically was, so adding yesterday's overage again would
inflate today's shortage by exactly that amount.

For day 1 of the first accounting month there is no previous working day,
so Previous Balance comes from OpeningInventory (0 by default, or a
user-supplied value).
"""

import datetime
from decimal import Decimal

from django.db.models import Sum

from .models import TankInventory, OpeningInventory
from apps.purchases.models import PurchaseInvoice
from apps.sales.models import NozzleSale
from apps.workday import services as workday_services


def _sum_or_zero(queryset, field) -> Decimal:
    result = queryset.aggregate(total=Sum(field))["total"]
    return result if result is not None else Decimal("0")


def get_daily_purchase_total(tank, working_day) -> Decimal:
    qs = PurchaseInvoice.objects.filter(tank=tank, working_day=working_day)
    return _sum_or_zero(qs, "quantity")


def get_test_return(tank, working_day) -> Decimal:
    qs = NozzleSale.objects.filter(
        nozzle__tank=tank, sales_invoice__working_day=working_day
    )
    return _sum_or_zero(qs, "test")


def get_daily_sales(tank, working_day) -> Decimal:
    """Sum of mechanical sales (a derived property, not a stored column)
    for all nozzles of this tank on this working day."""
    qs = NozzleSale.objects.filter(
        nozzle__tank=tank, sales_invoice__working_day=working_day
    )
    total = Decimal("0")
    for sale in qs:
        total += sale.mechanical_sales
    return total


def _get_previous_working_day_inventory(tank, working_day):
    """The immediately preceding TankInventory row for this tank, strictly
    before `working_day.date`. Returns None if there is none (i.e. this is
    the first working day ever recorded for this tank)."""
    return (
        TankInventory.objects.filter(
            tank=tank, working_day__date__lt=working_day.date
        )
        .order_by("-working_day__date")
        .first()
    )


def get_previous_balance(tank, working_day) -> Decimal:
    """
    The Previous Balance (موجودی واقعی روز قبل) as a Decimal.

    - If a previous TankInventory row exists for this tank: that row's
      actual_inventory. (Its overage/shortage plays no part -- see the
      module docstring.)
    - Otherwise (this is day 1 of the first accounting month for this
      tank): OpeningInventory.opening_quantity for the accounting start
      month (0 if none was supplied).
    """
    previous_row = _get_previous_working_day_inventory(tank, working_day)

    if previous_row is not None:
        return previous_row.actual_inventory

    accounting_start = workday_services.get_accounting_start_date()
    opening = None
    if accounting_start is not None:
        opening = OpeningInventory.objects.filter(
            tank=tank, effective_month=accounting_start
        ).first()

    return opening.opening_quantity if opening else Decimal("0")


def compute_theoretical_inventory(total_inventory, daily_sales, test_return):
    """
    موجودی تئوری = موجودی کل − (فروش مکانیکی + آزمایش).

    Everything that passed through the nozzle meters that day -- the
    OPERATION -- is mechanical sales plus test (operation = sales + test).
    The test liters go back into the tank, and the total inventory already
    counts them as returned (جمع کل includes "بازگشت از آزمایش"), so they
    must also be counted as having gone out through the meter; otherwise the
    test would be added once and never subtracted, and a day with a test of
    T would show T too little in the tank (a shortage of T on a perfect day).
    Net effect on the tank = −sales: the test cancels.

    One definition, shared by compute_tank_inventory() and the daily
    actual-inventory entry page so the two can never disagree.
    """
    return total_inventory - (daily_sales + test_return)


def compute_tank_inventory(tank, working_day):
    """
    Computes this working day's (total_inventory, theoretical_inventory,
    shortage, overage) for `tank`, where
        total_inventory       = previous actual + purchases + test
        theoretical_inventory = total_inventory - (mechanical sales + test)
    (see compute_theoretical_inventory() for why the test is subtracted), using only:
      - the previous working day's ACTUAL inventory (never any overage or
        shortage -- neither the previous day's nor this day's own), and
      - this day's own source data (purchases, tests, sales).

    Requires a TankInventory row to already exist for (tank, working_day)
    with actual_inventory set -- Actual Inventory is always manually
    entered by the operator, never computed.

    Returns (total_inventory, theoretical_inventory, shortage, overage) as
    Decimals, with shortage/overage always non-negative.
    """
    try:
        inventory_row = TankInventory.objects.get(tank=tank, working_day=working_day)
    except TankInventory.DoesNotExist as exc:
        raise ValueError(
            "Actual inventory has not been entered for this tank/day yet; "
            "cannot compute derived inventory values."
        ) from exc

    previous_balance = get_previous_balance(tank, working_day)

    daily_purchase = get_daily_purchase_total(tank, working_day)
    test_return = get_test_return(tank, working_day)
    daily_sales = get_daily_sales(tank, working_day)

    total_inventory = previous_balance + daily_purchase + test_return
    theoretical_inventory = compute_theoretical_inventory(
        total_inventory, daily_sales, test_return
    )
    actual_inventory = inventory_row.actual_inventory

    if theoretical_inventory > actual_inventory:
        shortage = theoretical_inventory - actual_inventory
        overage = Decimal("0")
    elif actual_inventory > theoretical_inventory:
        overage = actual_inventory - theoretical_inventory
        shortage = Decimal("0")
    else:
        shortage = Decimal("0")
        overage = Decimal("0")

    return total_inventory, theoretical_inventory, shortage, overage


def get_shortage(tank, working_day) -> Decimal:
    return compute_tank_inventory(tank, working_day)[2]


def get_overage(tank, working_day) -> Decimal:
    return compute_tank_inventory(tank, working_day)[3]
