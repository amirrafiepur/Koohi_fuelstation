"""
"صورت وضعیت ماهانه" (Monthly Statement) aggregation.

Like apps/reports/services.py, this is a read-only derived view: nothing
here is stored except the two operator-entered fields on StatementEntry
(digital_sales, tanker_capacity -- see apps/statement/models.py).

The main رسیده/خارج شده table reuses
apps.reports.services.petroleum_inventory_monthly() verbatim for every
value it already computes (beginning/ending inventory, purchase/test/
sales/shortage/overage totals, and جمع کل رسیده ها) -- no calculation is
duplicated here. Only the two formulas the task explicitly hands us
(commission and the unauthorized-shortage split) are new, and both are
implemented exactly as given, from those same reused totals.
"""

from decimal import Decimal

from apps.core.jalali import jalali_month_bounds
from apps.purchases.models import PurchaseInvoice
from apps.reports import services as report_services
from apps.stations.models import Tank

from .models import StatementEntry

TWO_PLACES = Decimal("0.01")


#: "لیتراژ غیرمجاز" is displayed only when "پورسانت" reaches this value; below
#: it the fuel is considered authorized and 0 is shown (calculation untouched).
UNAUTHORIZED_DISPLAY_COMMISSION_THRESHOLD = Decimal("45")


def build_statement_rows(year: int, month: int):
    """
    One row per tank/product for the selected Jalali year/month. Always
    one row per existing tank (never skipped for having no data that
    month), so both "بنزین معمولی" and "بنزین سوپر" always appear.
    """
    first_day, last_day = jalali_month_bounds(year, month)
    tanks = Tank.objects.select_related("product").order_by("product__name")

    rows = []
    for tank in tanks:
        monthly = report_services.petroleum_inventory_monthly(tank, year, month)
        if monthly is None:
            # No working days registered yet this month for this tank --
            # still show the row (per the task's explicit two-product-rows
            # requirement), with the underlying totals at zero/blank
            # rather than inventing a nonexistent report.
            beginning_inventory = Decimal("0")
            ending_inventory = None
            total_purchase = Decimal("0")
            total_test_return = Decimal("0")
            total_sales = Decimal("0")
            total_shortage = Decimal("0")
            total_overage = Decimal("0")
            total_received = None
        else:
            beginning_inventory = monthly["beginning_inventory"]
            ending_inventory = monthly["ending_inventory"]
            total_purchase = monthly["total_purchase"]
            total_test_return = monthly["total_test_return"]
            total_sales = monthly["total_sales"]
            total_shortage = monthly["total_shortage"]
            total_overage = monthly["total_overage"]
            total_received = monthly["total_received"]

        # "جمع کل" (رسیده side) = موجودی اول ماه + مقدار رسیده + آزمایش + سرک
        received_total = beginning_inventory + total_purchase + total_test_return + total_overage

        # "جمع کل خارج شده" -- per the task's explicit formula (this is a
        # different total from petroleum_inventory_monthly()'s own
        # total_dispatched, which is a running per-day sum that adds the
        # actual inventory of every day, not just the end-of-month one;
        # this section's own formula uses only the end-of-month inventory).
        dispatched_total = (
            total_sales + total_test_return + total_shortage + (ending_inventory or Decimal("0"))
        )

        # تعداد نفتکش: number of purchase invoices for this tank this
        # month -- a straight count, never derived from liters or from
        # شماره ی نفتکش.
        tanker_count = PurchaseInvoice.objects.filter(
            tank=tank, working_day__date__gte=first_day, working_day__date__lte=last_day,
        ).count()

        # پورسانت = (کسری × 10000) ÷ مقدار رسیده -- exact formula, no
        # substitute. مقدار رسیده here is the SAME upper-table value used
        # elsewhere in this function (total_purchase), for this tank's
        # selected month; کسری is the same total_shortage used elsewhere
        # too -- no separate computation. Guarded against a month with no
        # purchases (مقدار رسیده = 0), where the ratio is undefined; 0 is
        # the safe result rather than a crash.
        if total_purchase:
            commission = (total_shortage * Decimal("10000") / total_purchase).quantize(TWO_PLACES)
        else:
            commission = Decimal("0.00")

        # کسری مجاز = (مقدار رسیده × 45) ÷ 10000
        allowed_shortage = (total_purchase * Decimal("45") / Decimal("10000")).quantize(TWO_PLACES)
        # کسری غیرمجاز = کسری کل − کسری مجاز
        unauthorized_shortage = (total_shortage - allowed_shortage).quantize(TWO_PLACES)

        # DISPLAY rule only -- the calculation above is unchanged. Below the
        # commission threshold the shortage counts as authorized, so the
        # statement (screen and PDF) shows 0 for کسری غیرمجاز instead of the
        # calculated figure. The comparison uses the commission exactly as
        # it is shown (two decimals), so what the reader sees is consistent.
        unauthorized_shortage_shown = (
            unauthorized_shortage if commission >= UNAUTHORIZED_DISPLAY_COMMISSION_THRESHOLD
            else Decimal("0.00")
        )

        entry, _ = StatementEntry.objects.get_or_create(tank=tank, year=year, month=month)

        digital_sales_difference = None
        if entry.digital_sales is not None:
            # اختلاف فروش دیجیتال و مکانیکی: مقدار فروش (مکانیکی، همان
            # total_sales بالا) منهای فروش دیجیتال واردشده.
            digital_sales_difference = total_sales - entry.digital_sales

        rows.append({
            "tank": tank,
            "product": tank.product,
            "beginning_inventory": beginning_inventory,
            "total_purchase": total_purchase,
            "total_test_return": total_test_return,
            "total_overage": total_overage,
            "received_total": received_total,
            "total_received": total_received,
            "total_sales": total_sales,
            "total_shortage": total_shortage,
            "ending_inventory": ending_inventory,
            "dispatched_total": dispatched_total,
            "tanker_count": tanker_count,
            "commission": commission,
            "allowed_shortage": allowed_shortage,
            "unauthorized_shortage": unauthorized_shortage,
            "unauthorized_shortage_shown": unauthorized_shortage_shown,
            "entry": entry,
            "digital_sales": entry.digital_sales,
            "digital_sales_difference": digital_sales_difference,
            "tanker_capacity": entry.tanker_capacity,
        })
    return rows
