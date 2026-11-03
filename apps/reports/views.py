"""
Report views: read-only derived views that call reports/services.py
aggregations and render them without any business logic in the template.
"""

import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.core.jalali import current_jalali_year_month, jalali_month_bounds
from apps.stations.models import Nozzle, Product, Tank
from apps.workday import services as workday_services

from . import services as report_services


@login_required
def nozzle_performance_ledger(request, nozzle_id=None):
    """
    Nozzle Performance Ledger (F5): per-nozzle daily breakdown showing
    Operation/Mechanical Sales/Sales/Total Amount for a date range.
    """
    today = workday_services.get_today()
    accounting_start = workday_services.get_accounting_start_date()

    # Default date range: the current JALALI month (the period the
    # operator actually thinks in), not the Gregorian calendar month --
    # start_date is day 1 of the current Jalali month, converted to
    # Gregorian for the query, so its Jalali display is correctly
    # "1405/06/01" rather than a mid-month Gregorian date reinterpreted
    # as Jalali.
    jalali_year, jalali_month = current_jalali_year_month(today)
    start_date, _ = jalali_month_bounds(jalali_year, jalali_month)
    end_date = today

    if request.GET.get("nozzle_id"):
        nozzle_id = int(request.GET.get("nozzle_id"))
    if request.GET.get("start_date"):
        start_date = datetime.date.fromisoformat(request.GET.get("start_date"))
    if request.GET.get("end_date"):
        end_date = datetime.date.fromisoformat(request.GET.get("end_date"))

    nozzles = Nozzle.objects.select_related("tank__product").order_by("number")
    selected_nozzle = None
    rows = []

    if nozzle_id:
        selected_nozzle = Nozzle.objects.get(pk=nozzle_id)
        rows = report_services.nozzle_performance_ledger(
            selected_nozzle, start_date, end_date
        )

    return render(
        request, "reports/nozzle_performance_ledger.html",
        {
            "nozzles": nozzles,
            "selected_nozzle": selected_nozzle,
            "rows": rows,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@login_required
def all_nozzles_performance(request):
    """
    لیست اطلاعات فروش: a monthly, nozzle-based report for one fuel type. The
    operator picks a JALALI year/month and the fuel (بنزین معمولی / سوپر --
    the same tank selector the petroleum reports use); the table lists only
    that fuel's nozzles, with a summary strip of column totals above it.
    Regular and Super nozzles are never mixed. A deliberately separate
    view/URL from nozzle_performance_ledger() (the per-nozzle daily ledger).
    """
    today = workday_services.get_today()
    default_year, default_month = current_jalali_year_month(today)
    year = int(request.GET.get("year", default_year))
    month = int(request.GET.get("month", default_month))

    tanks = list(Tank.objects.select_related("product").order_by("product__name"))
    if request.GET.get("tank_id"):
        selected_tank = get_object_or_404(Tank.objects.select_related("product"), pk=int(request.GET["tank_id"]))
    else:
        selected_tank = tanks[0] if tanks else None          # Regular sorts first

    rows = report_services.all_nozzles_monthly_summary(year, month, selected_tank) if selected_tank else []
    totals = report_services.all_nozzles_monthly_totals(rows)

    return render(
        request, "reports/all_nozzles_performance.html",
        {"rows": rows, "totals": totals, "year": year, "month": month,
         "tanks": tanks, "selected_tank": selected_tank},
    )


@login_required
def nozzle_performance_monthly(request):
    """
    Monthly Nozzle Performance Report: per-nozzle monthly totals for a
    chosen year/month.

    year/month here are JALALI (the operator picks/reads e.g. 1405/06,
    not a Gregorian month) -- see reports/services.py's
    nozzle_performance_monthly() docstring.
    """
    today = workday_services.get_today()
    default_year, default_month = current_jalali_year_month(today)
    year = int(request.GET.get("year", default_year))
    month = int(request.GET.get("month", default_month))

    nozzles = Nozzle.objects.select_related("tank__product").order_by("number")
    rows = []

    for nozzle in nozzles:
        report = report_services.nozzle_performance_monthly(nozzle, year, month)
        if report:
            rows.append(report)

    return render(
        request, "reports/nozzle_performance_monthly.html",
        {"rows": rows, "year": year, "month": month},
    )


@login_required
def petroleum_inventory_operations_ledger(request, tank_id=None):
    """
    Petroleum Inventory & Operations Ledger (F6): per-tank daily breakdown
    showing Purchases/Test Returns/Sales/Inventory computations for a date
    range.
    """
    today = workday_services.get_today()
    accounting_start = workday_services.get_accounting_start_date()

    # Default date range: current JALALI month -- see the identical
    # comment in nozzle_performance_ledger() above.
    jalali_year, jalali_month = current_jalali_year_month(today)
    start_date, _ = jalali_month_bounds(jalali_year, jalali_month)
    end_date = today

    if request.GET.get("tank_id"):
        tank_id = int(request.GET.get("tank_id"))
    if request.GET.get("start_date"):
        start_date = datetime.date.fromisoformat(request.GET.get("start_date"))
    if request.GET.get("end_date"):
        end_date = datetime.date.fromisoformat(request.GET.get("end_date"))

    tanks = Tank.objects.select_related("product").order_by("product__name")
    selected_tank = None
    rows = []
    totals = None

    if tank_id:
        selected_tank = Tank.objects.get(pk=tank_id)
        rows = report_services.petroleum_inventory_operations_ledger(
            selected_tank, start_date, end_date
        )
        # "مجموع اطلاعات": totals of exactly the rows displayed below.
        totals = report_services.petroleum_inventory_ledger_totals(rows)

    return render(
        request, "reports/petroleum_inventory_ledger.html",
        {
            "tanks": tanks,
            "selected_tank": selected_tank,
            "rows": rows,
            "totals": totals,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@login_required
def petroleum_inventory_monthly(request):
    """
    Monthly Tank Statement: per-tank monthly totals for a chosen year/month.

    year/month here are JALALI -- see
    reports/services.py's petroleum_inventory_monthly() docstring.
    """
    today = workday_services.get_today()
    default_year, default_month = current_jalali_year_month(today)
    year = int(request.GET.get("year", default_year))
    month = int(request.GET.get("month", default_month))

    tanks = Tank.objects.select_related("product").order_by("product__name")
    rows = []

    for tank in tanks:
        report = report_services.petroleum_inventory_monthly(tank, year, month)
        if report:
            rows.append(report)

    return render(
        request, "reports/petroleum_inventory_monthly.html",
        {"rows": rows, "year": year, "month": month},
    )
