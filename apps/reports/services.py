"""
Report aggregation services. All reports are read-only derived views over
existing source-of-truth data. No stored columns, no materialized summaries.

Each aggregation function returns raw data structures (lists of dicts) ready
for template rendering -- never stored in the database.
"""

from decimal import Decimal

from apps.sales.models import SalesInvoice, NozzleSale
from apps.purchases.models import PurchaseInvoice
from apps.inventory import services as inventory_services
from apps.inventory.models import TankInventory
from apps.stations.models import Nozzle, Tank
from apps.workday.models import DailyWorkingDay


def nozzle_performance_ledger(nozzle: Nozzle, start_date, end_date):
    """
    Nozzle Performance Ledger (F5): per nozzle, one row per working day
    from start_date through end_date. All derived from NozzleSale records
    -- previous_meter, test, and new_meter are the exact values entered
    on the sales form (apps/sales/models.py:NozzleSale); operation,
    mechanical_sales, sales_amount, and total_amount reuse that model's
    existing derived properties verbatim (no duplicate calculation here).

    daily_total ("جمع روزانه") = mechanical_sales + test. This is
    algebraically identical to operation (since mechanical_sales =
    operation - test by definition), which is expected, not a bug --
    both are shown as separate columns because they answer different
    questions (net sales-with-test-added-back vs. raw meter movement).

    cumulative_total ("جمع کل") is the running sum of daily_total across
    this row set, in date order: first row's cumulative_total equals its
    own daily_total, and each later row adds its daily_total to the
    previous row's cumulative_total. It resets to start fresh for each
    call (i.e. for each selected date range), and is computed purely
    from daily_total here -- no separate/duplicate accumulation logic.
    """
    rows = []
    cumulative_total = None
    for wd in DailyWorkingDay.objects.filter(
        date__gte=start_date, date__lte=end_date
    ).order_by("date"):
        sale = NozzleSale.objects.filter(
            nozzle=nozzle, sales_invoice__working_day=wd
        ).first()

        if sale:
            daily_total = sale.mechanical_sales + sale.test
            cumulative_total = (
                daily_total if cumulative_total is None else cumulative_total + daily_total
            )
            rows.append({
                "date": wd.date,
                "nozzle": nozzle,
                "previous_meter": sale.previous_meter,
                "new_meter": sale.new_meter,
                "test": sale.test,
                "operation": sale.operation,
                "mechanical_sales": sale.mechanical_sales,
                "daily_total": daily_total,
                "cumulative_total": cumulative_total,
                "sales_amount": sale.sales_amount,
                "sales_rate": sale.sales_rate,
                "total_amount": sale.total_amount,
            })
    return rows


def all_nozzles_monthly_summary(year: int, month: int, tank):
    """
    "لیست اطلاعات فروش": a monthly, nozzle-based report for ONE fuel type.
    `tank` selects the fuel (Regular or CNG); the report lists exactly the
    nozzles that belong to that tank -- from the data model, in nozzle-number
    order (the seeded station gives Regular: 1-14 = 14 nozzles, and
    CNG: CNG 1-4 = 4 nozzles) -- and never a nozzle of the other fuel. Each
    row holds that nozzle's figures over the selected JALALI year/month
    (converted to a Gregorian range with jalali_month_bounds(), like every
    other monthly report):

        first_meter             کنتور اول ماه  (کنتور قبلی on the first recorded day)
        last_meter              کنتور آخر ماه  (کنتور جدید on the last recorded day)
        total_mechanical_sales  جمع فروش مکانیکی
        total_test              جمع آزمایش
        total_operation         جمع کارکرد
        total_amount            جمع مبلغ کل   (feeds the summary strip; not a table column)

    Reuses NozzleSale's existing operation / test / mechanical_sales /
    total_amount values verbatim for every sale in the month -- no new
    formulas. A nozzle of this fuel with no sales that month still gets its
    row, with zeros and "—" counters.
    """
    from apps.core.jalali import jalali_month_bounds

    first_day, last_day = jalali_month_bounds(year, month)

    # Chronological (date, then id) so the first and last record of each
    # nozzle are its first and last RECORDED working day of the month --
    # never an assumed 1st / last calendar day.
    sales = NozzleSale.objects.filter(
        nozzle__tank=tank,
        sales_invoice__working_day__date__gte=first_day,
        sales_invoice__working_day__date__lte=last_day,
    ).select_related("nozzle", "sales_invoice__working_day").order_by(
        "sales_invoice__working_day__date", "id"
    )

    zero = Decimal("0")
    by_number = {}
    for sale in sales:
        acc = by_number.setdefault(
            sale.nozzle.number,
            {"total_operation": zero, "total_test": zero,
             "total_mechanical_sales": zero, "total_amount": zero,
             # کنتور اول ماه: کنتور قبلی of the nozzle's first recorded day.
             "first_meter": sale.previous_meter, "last_meter": None},
        )
        acc["last_meter"] = sale.new_meter          # ends as کنتور جدید of the last recorded day
        acc["total_operation"] += sale.operation
        acc["total_test"] += sale.test
        acc["total_mechanical_sales"] += sale.mechanical_sales
        acc["total_amount"] += sale.total_amount

    rows = []
    for nozzle in Nozzle.objects.filter(tank=tank).select_related("tank__product").order_by("number"):
        number = nozzle.number
        acc = by_number.get(number)
        rows.append({
            "nozzle_number": number,
            "nozzle_identifier": nozzle.identifier,       # "5" / "CNG 1" -- what the report shows
            "total_operation": acc["total_operation"] if acc else zero,
            "total_test": acc["total_test"] if acc else zero,
            "total_mechanical_sales": acc["total_mechanical_sales"] if acc else zero,
            "total_amount": acc["total_amount"] if acc else zero,
            # Counter readings; None (shown as "—") for a nozzle with no
            # sales record that month -- a missing record is not a reading of 0.
            "first_meter": acc["first_meter"] if acc else None,
            "last_meter": acc["last_meter"] if acc else None,
        })
    return rows


def all_nozzles_monthly_totals(rows):
    """
    The monthly summary strip above the table: each total is the sum of
    that column over exactly the rows passed in (the selected fuel's
    nozzles, as displayed),
    so the summary can never disagree with the table beneath it.
    """
    zero = Decimal("0")
    return {
        "total_operation": sum((r["total_operation"] for r in rows), zero),
        "total_test": sum((r["total_test"] for r in rows), zero),
        "total_mechanical_sales": sum((r["total_mechanical_sales"] for r in rows), zero),
        "total_amount": sum((r["total_amount"] for r in rows), zero),
    }


def nozzle_performance_monthly(nozzle: Nozzle, year: int, month: int):
    """
    Monthly Nozzle Performance Report: one row per nozzle per month,
    showing totals plus beginning/end-of-month meter readings.

    `year`/`month` are the operator-facing JALALI year/month (e.g.
    1405/06) -- the report period the operator actually selects and
    reads is a Jalali month, not a Gregorian one. They are converted to
    a Gregorian [first_day, last_day] range via jalali_month_bounds()
    for the actual DB query; everything below this point continues to
    work in plain Gregorian dates exactly as before.

    Beginning-of-month meter = the previous month's ending meter for this
    nozzle, determined chronologically from actual NozzleSale records --
    never hardcoded. For the FIRST accounting month specifically, the
    beginning-of-month meter is instead this nozzle's meter reading on
    day 1 of that month (the first working day actually entered), since
    no prior month's records exist to carry forward from.

    End-of-month meter = the New Meter of the latest registered
    NozzleSale within the selected period.
    """
    from apps.core.jalali import jalali_month_bounds

    first_day, last_day = jalali_month_bounds(year, month)

    rows = NozzleSale.objects.filter(
        nozzle=nozzle,
        sales_invoice__working_day__date__gte=first_day,
        sales_invoice__working_day__date__lte=last_day,
    ).select_related("sales_invoice__working_day").order_by(
        "sales_invoice__working_day__date"
    )

    if not rows.exists():
        return None

    total_operation = sum(r.operation for r in rows) or Decimal("0")
    total_mechanical_sales = sum(r.mechanical_sales for r in rows) or Decimal("0")
    total_sales_amount = sum(r.sales_amount for r in rows) or Decimal("0")
    total_amount = sum(r.total_amount for r in rows) or Decimal("0")

    # End-of-month meter: New Meter of the latest working day in this
    # period that has a registered sale for this nozzle.
    end_of_month_meter = rows.last().new_meter

    # Beginning-of-month meter: determined chronologically, never
    # hardcoded. Normally this is the previous month's ending meter for
    # this nozzle -- found by looking at the latest NozzleSale strictly
    # before this period's first day. For the FIRST accounting month (no
    # such prior record exists for this nozzle), it falls back to this
    # nozzle's own first entry within the period -- its meter reading on
    # day 1 of that month, exactly as recorded by the operator.
    prior_sale = (
        NozzleSale.objects.filter(
            nozzle=nozzle,
            sales_invoice__working_day__date__lt=first_day,
        )
        .order_by("-sales_invoice__working_day__date")
        .first()
    )
    if prior_sale is not None:
        beginning_of_month_meter = prior_sale.new_meter
    else:
        beginning_of_month_meter = rows.first().previous_meter

    return {
        "nozzle": nozzle,
        "year": year,
        "month": month,
        "beginning_of_month_meter": beginning_of_month_meter,
        "end_of_month_meter": end_of_month_meter,
        "total_operation": total_operation,
        "total_mechanical_sales": total_mechanical_sales,
        "total_sales_amount": total_sales_amount,
        "total_amount": total_amount,
    }


def _is_first_working_day_of_jalali_month(day) -> bool:
    """True when no earlier DailyWorkingDay exists in the same JALALI month as `day`
    (so `day` is that month's first working day -- not necessarily its 1st calendar day)."""
    from apps.core.jalali import current_jalali_year_month, jalali_month_bounds

    year, month = current_jalali_year_month(day)
    first_day, _ = jalali_month_bounds(year, month)
    return not DailyWorkingDay.objects.filter(date__gte=first_day, date__lt=day).exists()


def previous_actual_inventory_before(tank: Tank, before_date):
    """
    موجودی واقعی of the last recorded TankInventory row for `tank` strictly
    before `before_date` (i.e. the last recorded date of the previous
    month when `before_date` is a month's first working day), or None if
    the tank has no earlier recorded day (the tank's first working month,
    where موجودی افتتاحیه is used instead).
    """
    return (
        TankInventory.objects.filter(tank=tank, working_day__date__lt=before_date)
        .order_by("-working_day__date")
        .values_list("actual_inventory", flat=True)
        .first()
    )


def petroleum_inventory_operations_ledger(tank: Tank, start_date, end_date):
    """
    "دفتر موجودی و عملیات": per tank, one row per working day from
    start_date through end_date, split into two symmetric sides:

    "رسیده" (received) -- per PurchaseInvoice for that day (0, 1, or many;
    see apps/purchases/tests.py's multi-invoice-per-day coverage), plus
    that day's aggregate Test/سرک/daily-total/cumulative-total, which are
    day-level values shown once per day (attached to the first purchase
    row; blank on any additional same-day purchase rows -- a standard
    ledger convention for a day-level total next to line-item detail).
    A day with zero purchases still gets exactly one "رسیده" row, so
    every DailyWorkingDay in range has at least one row on this side,
    matching "خارج شده" having exactly one row per day.

        جمع روزانه‌ی رسیده = مقدار خرید (day total) + مجموع آزمایش + سرک
        جمع کل رسیده (day N) = جمع کل رسیده (day N-1) + جمع روزانه‌ی رسیده (day N)

    "خارج شده" (dispatched) -- exactly one row per day:

        جمع روزانه‌ی خارج شده = جمع فروش مکانیکی + جمع آزمایش + کسری
        جمع کل خارج شده (day N) = جمع کل خارج شده (day N-1) + جمع روزانه‌ی خارج شده (day N)

    سرک/کسری reuse inventory_services.compute_tank_inventory()'s existing
    overage/shortage verbatim -- overage is سرک (0 when the day is a
    shortage day instead), shortage is کسری (0 when the day is an
    overage day instead); this is unchanged from before this rework, only
    relabeled per the UI-level renames already established elsewhere in
    this project (see apps/inventory's "موجودی غیرواقعی"/"سرک" renames).

    موجودی واقعی (actual_inventory) is still its own column on this row,
    stored and displayed exactly as the operator entered it, but it does
    NOT contribute to جمع روزانه‌ی خارج شده. An earlier version of this
    formula mistakenly added it in every day; that was wrong (موجودی
    واقعی is an absolute tank balance, not a daily outflow quantity, so
    summing it in daily double-counts the same balance over and over)
    and has been corrected to the formula above. This value is never
    persisted anywhere -- every call site (reports/views.py,
    printing/services.py, and this module's own
    petroleum_inventory_monthly() below, which reuses this cumulative
    total verbatim for "گزارش ماهانه مخازن") reads it fresh from this
    function on every request. So correcting the formula here is itself
    the complete historical correction: every past day is recomputed
    live from its original stored NozzleSale/PurchaseInvoice/
    TankInventory rows, with no stale stored value anywhere left to
    migrate. (apps.statement's "صورت وضعیت ماهانه" and apps.comparison
    never depended on this function's dispatched total at all -- see
    apps/statement/services.py's own, independent dispatched_total
    formula, which only ever used موجودی واقعی once, as the period's
    ending balance, never summed daily -- so that section was never
    affected by this bug and needs no change here.)

    Both cumulative totals follow the same carry-forward rule: every day
    after the first row of the selected range, جمع کل = روز قبل's جمع کل
    + امروز's جمع روزانه. جمع کل خارج شده does NOT reconcile against جمع
    کل رسیده (a running sum of small daily deltas) -- the two cumulative
    totals are independent running sums, not two views of the same
    underlying quantity.

    For جمع کل رسیده specifically, the first row of the selected range is
    NOT always seeded from 0: if that row is also this tank's actual
    first working day ever (no earlier TankInventory row exists for this
    tank at all), موجودی افتتاحیه is treated as "جمع کل رسیده of day
    zero" and carried in as the starting point -- reusing
    inventory_services.get_previous_balance_and_overage()'s existing
    OpeningInventory lookup (and its existing 0-default when none was
    supplied) verbatim, the same source already used for Total
    Inventory's own day-1 Previous Balance. A sub-range that starts later
    in an already-running tank's history (not the tank's true first
    working day) is unaffected by this and keeps the existing "starts
    from 0 for display purposes" convention. جمع کل خارج شده is
    untouched by this -- the task that introduced it only concerns جمع کل
    رسیده.

    MONTH CARRY-FORWARD. From the second working month onward, on a
    JALALI month's FIRST working day (for this tank: its first recorded
    day of the month),

        جمع کل رسیده = موجودی واقعی آخرین تاریخ ثبت‌شده ماه قبل + جمع روزانه‌ی رسیده همان روز

    and the following days of the month accumulate as usual. The previous
    month's جمع کل رسیده is NOT carried forward. The first working month
    keeps  جمع کل رسیده = موجودی افتتاحیه + جمع روزانه‌ی رسیده  on the
    tank's first day. The rule applies at every month boundary inside
    the selected range and when the range starts on a month's first
    working day (the normal month view); a range starting mid-month
    keeps the existing "starts from that day's own total" convention.
    """
    from apps.sales import services as sales_services
    from apps.purchases import services as purchase_services

    rows = []
    cumulative_received = None
    cumulative_dispatched = None

    working_days = DailyWorkingDay.objects.filter(
        date__gte=start_date, date__lte=end_date
    ).order_by("date")

    # Month carry-forward (see the docstring). `month_start_pending` is True
    # until the first recorded day of a Jalali month has been handled.
    from apps.core.jalali import current_jalali_year_month

    first_working_day = working_days.first()
    month_start_pending = (
        first_working_day is not None
        and _is_first_working_day_of_jalali_month(first_working_day.date)
    )
    current_month = None

    for wd in working_days:
        wd_month = current_jalali_year_month(wd.date)
        if current_month is not None and wd_month != current_month:
            month_start_pending = True
        current_month = wd_month

        purchases = list(
            PurchaseInvoice.objects.filter(tank=tank, working_day=wd).order_by("id")
        )
        daily_purchase = purchase_services.get_daily_purchase_total(tank, wd)
        test_return = inventory_services.get_test_return(tank, wd)
        daily_sales = sales_services.get_daily_sales(tank, wd)

        try:
            total_inventory, theoretical_inventory, shortage, overage = (
                inventory_services.compute_tank_inventory(tank, wd)
            )
        except ValueError:
            # TankInventory missing -- skip this day
            total_inventory = theoretical_inventory = shortage = overage = None

        daily_received = None
        daily_dispatched = None
        actual_inventory = None
        if overage is not None:
            actual_inventory = TankInventory.objects.filter(
                tank=tank, working_day=wd
            ).values_list("actual_inventory", flat=True).first()
            daily_received = daily_purchase + test_return + overage
            # جمع روزانه خارج شده = جمع فروش مکانیکی + مجموع آزمایش + کسری
            # -- موجودی واقعی (actual_inventory, still stored/displayed as
            # its own column below) does NOT contribute to this sum. It
            # previously did by mistake; see this function's own
            # docstring for the historical-correction note -- fixing this
            # formula is itself the complete correction, because this
            # value has never been persisted anywhere (see that note).
            daily_dispatched = daily_sales + test_return + shortage

            month_start_received = None
            if month_start_pending:
                month_start_pending = False
                previous_actual = previous_actual_inventory_before(tank, wd.date)
                if previous_actual is not None:
                    month_start_received = previous_actual + daily_received

            if month_start_received is not None:
                cumulative_received = month_start_received
            elif cumulative_received is None:
                is_tanks_first_working_day = not TankInventory.objects.filter(
                    tank=tank, working_day__date__lt=wd.date
                ).exists()
                if is_tanks_first_working_day:
                    opening_balance, _ = inventory_services.get_previous_balance_and_overage(tank, wd)
                    cumulative_received = opening_balance + daily_received
                else:
                    cumulative_received = daily_received
            else:
                cumulative_received = cumulative_received + daily_received
            cumulative_dispatched = (
                daily_dispatched if cumulative_dispatched is None else cumulative_dispatched + daily_dispatched
            )

        # "رسیده": one row per purchase invoice that day (or a single
        # placeholder row if there were none), day-level totals attached
        # only to the first such row.
        received_rows = []
        for i, invoice in enumerate(purchases or [None]):
            received_rows.append({
                "program_number": invoice.program_number if invoice else None,
                "tanker_number": invoice.tanker_number if invoice else None,
                "quantity": invoice.quantity if invoice else None,
                "test_return": test_return if i == 0 else None,
                "overage": overage if i == 0 else None,
                "daily_received": daily_received if i == 0 else None,
                "cumulative_received": cumulative_received if i == 0 else None,
            })

        rows.append({
            "date": wd.date,
            "tank": tank,
            "received_rows": received_rows,
            "daily_purchase": daily_purchase,
            "test_return": test_return,
            "daily_sales": daily_sales,
            "total_inventory": total_inventory,
            "theoretical_inventory": theoretical_inventory,
            "shortage": shortage,
            "overage": overage,
            "actual_inventory": actual_inventory,
            "daily_received": daily_received,
            "cumulative_received": cumulative_received,
            "daily_dispatched": daily_dispatched,
            "cumulative_dispatched": cumulative_dispatched,
            # Kept for backward compatibility with anything still reading
            # the pre-rework key names (daily_total_1/2 were exactly
            # daily_received/daily_dispatched already).
            "daily_total_1": daily_received,
            "daily_total_2": daily_dispatched,
        })
    return rows


def petroleum_inventory_ledger_totals(rows):
    """
    "مجموع اطلاعات" for "دفتر موجودی و عملیات": the totals of the rows the
    ledger is DISPLAYING for the selected tank and date range -- `rows` is
    exactly what petroleum_inventory_operations_ledger() returned for that
    range, so changing the range changes the rows and therefore the totals
    (nothing is stored or cached; the screen and the PDF both call this on
    the same rows).

    Each total sums the same cells the table shows in that column:

        total_purchase        مجموع خرید   -- every "مقدار خرید" (one per purchase invoice)
        total_overage         مجموع سرک    -- every "سرک"
        total_test_received   مجموع آزمایش -- every "مجموع آزمایش" cell on the رسیده side
        total_sales           مجموع فروش   -- every "جمع فروش مکانیکی"
        total_shortage        مجموع کسری   -- every "کسری"
        total_test_dispatched مجموع آزمایش -- every "جمع آزمایش" cell on the خارج شده side

    The two test totals are summed independently from their own side of
    the table; they are equal because both sides show the same daily test
    return. Cells that are blank (a day whose actual inventory was never
    entered has no سرک/کسری, and a day's extra purchase rows carry no
    day-level values) contribute nothing, exactly as they show blank.
    """
    total_purchase = Decimal("0")
    total_overage = Decimal("0")
    total_test_received = Decimal("0")
    total_sales = Decimal("0")
    total_shortage = Decimal("0")
    total_test_dispatched = Decimal("0")

    for row in rows:
        for received in row["received_rows"]:
            if received["quantity"] is not None:
                total_purchase += received["quantity"]
            if received["overage"] is not None:
                total_overage += received["overage"]
            if received["test_return"] is not None:
                total_test_received += received["test_return"]
        if row["daily_sales"] is not None:
            total_sales += row["daily_sales"]
        if row["shortage"] is not None:
            total_shortage += row["shortage"]
        if row["test_return"] is not None:
            total_test_dispatched += row["test_return"]

    return {
        "total_purchase": total_purchase,
        "total_overage": total_overage,
        "total_test_received": total_test_received,
        "total_sales": total_sales,
        "total_shortage": total_shortage,
        "total_test_dispatched": total_test_dispatched,
    }


def petroleum_inventory_monthly(tank: Tank, year: int, month: int):
    """
    Monthly Tank Statement: one row per tank per month.

    `year`/`month` are the operator-facing JALALI year/month, converted
    to a Gregorian [first_day, last_day] range via jalali_month_bounds()
    -- see nozzle_performance_monthly()'s docstring above for why.

    Beginning Inventory = previous month's ending Actual Inventory for
    this tank, determined chronologically from the latest TankInventory
    row strictly before this period. For the FIRST accounting month (no
    such prior row exists), Beginning Inventory = OpeningInventory for
    day 1 of that month (0 by default, or the operator's supplied value).

    Ending Inventory = the Actual Inventory of the last registered
    TankInventory row within the selected period -- never manually
    entered or computed at the monthly level.

    total_received/total_dispatched ("جمع کل رسیده"/"جمع کل خارج شده" in
    the monthly report) reuse petroleum_inventory_operations_ledger()'s
    own cumulative running totals verbatim -- the last day within this
    month whose cumulative total was actually computed, not a fresh
    monthly sum.
    """
    from apps.core.jalali import jalali_month_bounds
    from apps.sales import services as sales_services
    from apps.purchases import services as purchase_services
    from apps.workday import services as workday_services

    first_day, last_day = jalali_month_bounds(year, month)

    working_days_in_period = DailyWorkingDay.objects.filter(
        date__gte=first_day, date__lte=last_day
    )

    if not working_days_in_period.exists():
        return None

    received_quantity_total = Decimal("0")
    test_return_total = Decimal("0")
    daily_sales_total = Decimal("0")
    shortage_total = Decimal("0")
    overage_total = Decimal("0")

    for wd in working_days_in_period:
        received_quantity_total += purchase_services.get_daily_purchase_total(tank, wd)
        test_return_total += inventory_services.get_test_return(tank, wd)
        daily_sales_total += sales_services.get_daily_sales(tank, wd)
        try:
            _, _, shortage, overage = inventory_services.compute_tank_inventory(tank, wd)
            shortage_total += shortage
            overage_total += overage
        except ValueError:
            pass

    # Beginning Inventory: previous month's ending Actual Inventory,
    # found chronologically -- the latest TankInventory row for this
    # tank strictly before this period's first day.
    prior_inventory_row = (
        TankInventory.objects.filter(tank=tank, working_day__date__lt=first_day)
        .order_by("-working_day__date")
        .first()
    )
    if prior_inventory_row is not None:
        beginning_inventory = prior_inventory_row.actual_inventory
    else:
        accounting_start = workday_services.get_accounting_start_date()
        opening = None
        if accounting_start is not None:
            from apps.inventory.models import OpeningInventory
            opening = OpeningInventory.objects.filter(
                tank=tank, effective_month=accounting_start
            ).first()
        beginning_inventory = opening.opening_quantity if opening else Decimal("0")

    # Ending Inventory: Actual Inventory of the last registered
    # TankInventory row within this period -- auto-derived, never
    # manually entered at the monthly-report level.
    last_inventory_row = (
        TankInventory.objects.filter(
            tank=tank, working_day__date__gte=first_day, working_day__date__lte=last_day
        )
        .order_by("-working_day__date")
        .first()
    )
    ending_inventory = last_inventory_row.actual_inventory if last_inventory_row else None

    # جمع کل رسیده / جمع کل خارج شده: reused verbatim from دفتر موجودی و
    # عملیات's own cumulative running totals (see
    # petroleum_inventory_operations_ledger() above) -- not recomputed
    # here. "Last available value of the month" = the last day within
    # this period whose cumulative total was actually computed (a day
    # with no TankInventory row yet leaves it None there, exactly as in
    # that function, so such trailing days are skipped rather than
    # reported as 0).
    ledger_rows = petroleum_inventory_operations_ledger(tank, first_day, last_day)
    total_received = None
    total_dispatched = None
    for ledger_row in ledger_rows:
        if ledger_row["cumulative_received"] is not None:
            total_received = ledger_row["cumulative_received"]
        if ledger_row["cumulative_dispatched"] is not None:
            total_dispatched = ledger_row["cumulative_dispatched"]

    return {
        "tank": tank,
        "year": year,
        "month": month,
        "beginning_inventory": beginning_inventory,
        "ending_inventory": ending_inventory,
        "total_purchase": received_quantity_total,
        "total_test_return": test_return_total,
        "total_sales": daily_sales_total,
        "total_shortage": shortage_total,
        "total_overage": overage_total,
        "total_received": total_received,
        "total_dispatched": total_dispatched,
    }
