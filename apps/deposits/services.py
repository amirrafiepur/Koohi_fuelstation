"""
Deposit decade aggregation. Deposit.year/month/decade are already stored
on each row at creation time (see apps/deposits/views.py:_decade_for_date)
-- these functions only read/sum what's already there, never recompute or
duplicate the decade-assignment logic itself.
"""

from decimal import Decimal

from django.db.models import Sum

from apps.core.jalali import jalali_month_bounds, to_jalali

from .models import Deposit


def third_decade_length(year: int, month: int) -> int:
    """
    Number of days in the third decade (21 through end of month) for a
    given JALALI year/month -- 9, 10, or 11 days depending on whether
    the month has 29, 30, or 31 days. Derived from jalali_month_bounds()
    (already handles leap Esfand correctly) rather than a hardcoded
    29/30/31 table.
    """
    _, last_day = jalali_month_bounds(year, month)
    last_day_of_month = to_jalali(last_day).day
    return last_day_of_month - 20


def decade_totals(year: int, month: int) -> list[dict]:
    """
    One row per decade (اول/دوم/سوم) for the given JALALI year/month,
    each with its "جمع مبلغ واریزی" -- the sum of deposit_amount for
    every Deposit already assigned to that decade (via
    _decade_for_date() at creation time). A decade with no deposits
    still gets a row, with a total of 0 -- the three decades are always
    shown, per the section's own 3-row table requirement.
    """
    rows = []
    for decade_value, label in (
        (Deposit.FIRST_DECADE, "دهه اول"),
        (Deposit.SECOND_DECADE, "دهه دوم"),
        (Deposit.THIRD_DECADE, "دهه سوم"),
    ):
        total = Deposit.objects.filter(
            year=year, month=month, decade=decade_value
        ).aggregate(total=Sum("deposit_amount"))["total"]
        rows.append({
            "decade": decade_value,
            "label": label,
            "total": total or Decimal("0"),
        })
    return rows


def monthly_total(rows: list[dict]) -> Decimal:
    """
    "جمع مبلغ واریزی ماه" -- the sum of the three decade totals already
    computed by decade_totals(). Takes that function's own return value
    rather than re-querying, so this is never a second source of truth
    for the per-decade totals themselves.
    """
    return sum((row["total"] for row in rows), Decimal("0"))


def deposits_in_decade(year: int, month: int, decade: str):
    """
    Every Deposit already assigned to this JALALI year/month/decade
    (via _decade_for_date() at creation time), oldest date first.
    """
    return Deposit.objects.filter(
        year=year, month=month, decade=decade
    ).order_by("date")


def decade_total(year: int, month: int, decade: str) -> Decimal:
    """
    "مجموع واریزی دهه" for one decade of one JALALI month: the sum of
    deposit_amount over exactly the records deposits_in_decade() returns
    for that year/month/decade -- the same records the decade's table and
    PDF list -- so the figure on the summary and the rows beneath it can
    never disagree. Read-only; nothing is stored. Zero when the decade has
    no deposits.
    """
    total = deposits_in_decade(year, month, decade).aggregate(
        total=Sum("deposit_amount")
    )["total"]
    return total or Decimal("0")
