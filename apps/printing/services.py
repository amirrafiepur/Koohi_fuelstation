"""
Printing is a presentation/output layer only. Every printable report
pulls its data exclusively from reports/services.py (or, for the metadata
block, the Station model) -- this module NEVER recalculates a business
formula, NEVER stores a PDF-specific summary, and NEVER introduces a
second source of truth.

Each function here returns a template-ready context dict built entirely
from calls into the existing service layer.
"""

from apps.reports import services as report_services
from apps.stations.models import Station


#: Presentation-only mapping for the single seeded Station row (see
#: apps/stations/management/commands/seed_station.py), which still stores
#: its original English identity ("140 Jahan Pour" / "Razavi Khorasan" /
#: "Mashhad") -- per this project's Persianization task, the stored
#: values are deliberately left unchanged; only what gets printed is
#: translated. A station whose raw name doesn't match this known seed
#: value falls back to its raw DB fields unchanged below, so this never
#: breaks if the station row is ever renamed to something else.
_STATION_PERSIAN_DISPLAY = {
    "140 Jahan Pour": {
        "name": "جایگاه جهانی‌پور ۱۴۰",
        "province": "خراسان رضوی",
        "city": "مشهد",
    },
}


def get_station_metadata() -> dict:
    """
    Station identity block required on every printed report (name,
    province, city). Pulled live from the Station row; translated to its
    Persian display form for the known seeded station (see
    _STATION_PERSIAN_DISPLAY above) without altering the stored value.
    """
    station = Station.objects.first()
    if not station:
        return {"name": "", "province": "", "city": ""}

    persian = _STATION_PERSIAN_DISPLAY.get(station.name)
    if persian:
        return dict(persian)

    return {
        "name": station.name,
        "province": station.province,
        "city": station.city,
    }


def build_nozzle_ledger_context(nozzle, start_date, end_date) -> dict:
    """
    Reuses reports.services.nozzle_performance_ledger() verbatim -- the
    printed table is the exact same per-day rows shown on the on-screen
    ledger. The on-screen ledger has no totals row, so the print version
    must not invent one either (that would be a second, print-only
    calculation living outside reports/services.py).
    """
    rows = report_services.nozzle_performance_ledger(nozzle, start_date, end_date)
    return {
        "station": get_station_metadata(),
        "nozzle": nozzle,
        "start_date": start_date,
        "end_date": end_date,
        "rows": rows,
    }


def build_all_nozzles_performance_context(year: int, month: int, tank) -> dict:
    """
    Reuses reports.services.all_nozzles_monthly_summary() and
    all_nozzles_monthly_totals() verbatim for the selected fuel (`tank`) --
    the printed nozzle rows and the summary strip are exactly what the
    on-screen لیست اطلاعات فروش shows for that JALALI year/month and fuel.
    """
    rows = report_services.all_nozzles_monthly_summary(year, month, tank)
    return {
        "station": get_station_metadata(),
        "year": year,
        "month": month,
        "tank": tank,
        "rows": rows,
        "totals": report_services.all_nozzles_monthly_totals(rows),
    }


def build_nozzle_monthly_context(year: int, month: int) -> dict:
    """Reuses reports.services.nozzle_performance_monthly() per nozzle --
    identical rows/totals to the on-screen monthly report."""
    from apps.stations.models import Nozzle

    nozzles = Nozzle.objects.select_related("tank__product").order_by("number")
    rows = []
    for nozzle in nozzles:
        report = report_services.nozzle_performance_monthly(nozzle, year, month)
        if report:
            rows.append(report)

    return {
        "station": get_station_metadata(),
        "year": year,
        "month": month,
        "rows": rows,
    }


def build_petroleum_ledger_context(tank, start_date, end_date) -> dict:
    """Reuses reports.services.petroleum_inventory_operations_ledger()
    verbatim -- includes Daily Total 1/2, shortage/overage exactly as
    computed by inventory/services.py, no recalculation."""
    rows = report_services.petroleum_inventory_operations_ledger(tank, start_date, end_date)
    return {
        "station": get_station_metadata(),
        "tank": tank,
        "start_date": start_date,
        "end_date": end_date,
        "rows": rows,
        # "مجموع اطلاعات" -- same function and same rows as the screen.
        "totals": report_services.petroleum_inventory_ledger_totals(rows),
    }


def build_petroleum_monthly_context(year: int, month: int) -> dict:
    """Reuses reports.services.petroleum_inventory_monthly() per tank --
    identical beginning/ending inventory and totals to the on-screen
    monthly tank statement."""
    from apps.stations.models import Tank

    tanks = Tank.objects.select_related("product").order_by("product__name")
    rows = []
    for tank in tanks:
        report = report_services.petroleum_inventory_monthly(tank, year, month)
        if report:
            rows.append(report)

    return {
        "station": get_station_metadata(),
        "year": year,
        "month": month,
        "rows": rows,
    }


def build_deposit_decade_context(year: int, month: int, decade: str) -> dict:
    """
    Reuses deposits.services.deposits_in_decade() verbatim -- the printed
    table is exactly the deposits already shown on that decade's
    on-screen detail page (چاپ from دهه اول prints only دهه اول, etc.),
    no re-filtering here.
    """
    from apps.deposits import services as deposit_services
    from apps.deposits.models import Deposit

    decade_labels = {
        Deposit.FIRST_DECADE: "دهه اول",
        Deposit.SECOND_DECADE: "دهه دوم",
        Deposit.THIRD_DECADE: "دهه سوم",
    }

    return {
        "station": get_station_metadata(),
        "year": year,
        "month": month,
        "decade": decade,
        "decade_label": decade_labels[decade],
        "deposits": deposit_services.deposits_in_decade(year, month, decade),
        # "مجموع واریزی دهه" -- same function as the on-screen summary.
        "decade_total": deposit_services.decade_total(year, month, decade),
    }


def build_statement_context(year: int, month: int) -> dict:
    """
    "صورت وضعیت ماهانه": reuses apps.statement.services.build_statement_rows()
    verbatim, so the printed page shows exactly the same rows/values as
    the on-screen page for that year/month -- no recomputation here.
    """
    from apps.statement import services as statement_services

    return {
        "station": get_station_metadata(),
        "year": year,
        "month": month,
        "rows": statement_services.build_statement_rows(year, month),
    }


def build_comparison_context(year: int, month: int) -> dict:
    """
    "مقایسه سیستم مکانیکی و دیجیتال": reuses
    apps.comparison.services.build_mechanical_rows()/build_digital_rows()
    verbatim, so the printed page shows exactly the same two tables as
    the on-screen page for that year/month -- no recomputation here.
    """
    from apps.comparison import services as comparison_services

    return {
        "station": get_station_metadata(),
        "year": year,
        "month": month,
        "mechanical_rows": comparison_services.build_mechanical_rows(year, month),
        "digital_rows": comparison_services.build_digital_rows(year, month),
    }


def build_sales_invoice_context(working_day) -> dict:
    """
    "فاکتورهای فروش" daily invoice: reuses the exact same data sources as
    apps.sales.views.invoice_detail() (sales_services.get_daily_totals()
    and the same nozzle_sales queryset shape), so the PDF shows exactly
    what the on-screen page shows for that day -- no recalculation here.
    """
    from apps.sales import services as sales_services
    from apps.sales.models import SalesInvoice, NozzleSale

    invoice = SalesInvoice.objects.filter(working_day=working_day).first()
    nozzle_sales = (
        invoice.nozzle_sales.select_related("nozzle", "nozzle__tank__product").order_by("nozzle__number")
        if invoice
        else NozzleSale.objects.none()
    )
    totals = sales_services.get_daily_totals(working_day)

    return {
        "station": get_station_metadata(),
        "working_day": working_day,
        "nozzle_sales": nozzle_sales,
        "totals": totals,
    }


def build_seals_context(start_date, end_date) -> dict:
    """
    پلمپ‌ها date-range print: reuses the exact same NozzleSeal queryset
    shape as the on-screen list (apps/seals/views.py:seal_list) -- same
    filter, same ordering, no recalculation (there is nothing to
    calculate; this section has no derived values).
    """
    from apps.seals import services as seal_services

    seals = seal_services.seals_in_range(start_date, end_date)

    return {
        "station": get_station_metadata(),
        "start_date": start_date,
        "end_date": end_date,
        "seals": seals,
    }


def build_purchases_ledger_context(start_date, end_date) -> dict:
    """
    Reuses purchases.services.get_purchase_invoices_in_range() verbatim,
    once per tank -- identical PurchaseInvoice rows to the on-screen
    Purchases date-range list, split the same way into one entry per
    product/tank so the print template can render Regular and Super as
    two separate tables in the same PDF.
    """
    from apps.purchases import services as purchase_services
    from apps.stations.models import Tank

    tanks = Tank.objects.select_related("product").order_by("product__name")
    tank_rows = [
        {
            "tank": tank,
            "invoices": purchase_services.get_purchase_invoices_in_range(tank, start_date, end_date),
        }
        for tank in tanks
    ]

    return {
        "station": get_station_metadata(),
        "tank_rows": tank_rows,
        "start_date": start_date,
        "end_date": end_date,
    }
