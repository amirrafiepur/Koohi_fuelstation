"""
Printing views: each renders a print-specific Django template (reusing
the identical data contexts built in printing/services.py, which in turn
call reports/services.py exclusively) and converts the rendered HTML to a
PDF via WeasyPrint.

No accounting logic, no report aggregation, and no data queries beyond
what printing/services.py already assembled happen in this module -- it
is pure orchestration: build context -> render template -> convert to PDF.
"""

import datetime
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string

from apps.stations.models import Nozzle, Tank

from . import services as printing_services


def _render_pdf_response(template_name: str, context: dict, filename: str) -> HttpResponse:
    """
    Single shared HTML->PDF conversion path, so every printable report
    goes through identical A4/RTL page setup (see printing/base_print.html
    and static/css/print.css) with no per-report divergence.

    base_url is set to the static files directory on disk (not an HTTP
    URL) so WeasyPrint resolves the print stylesheet and font links via
    the filesystem -- this works identically whether Django is serving
    over HTTP or, in the packaged desktop build, has no separate "site"
    to fetch from at all.
    """
    import weasyprint
    from django.conf import settings

    html_string = render_to_string(template_name, context)
    static_dir = Path(settings.STATICFILES_DIRS[0]) if settings.STATICFILES_DIRS else Path(settings.BASE_DIR)
    pdf_bytes = weasyprint.HTML(
        string=html_string, base_url=static_dir.as_uri() + "/"
    ).write_pdf()

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


@login_required
def nozzle_ledger_print(request, nozzle_id):
    nozzle = Nozzle.objects.select_related("tank__product").get(pk=nozzle_id)

    start_date = datetime.date.fromisoformat(request.GET["start_date"])
    end_date = datetime.date.fromisoformat(request.GET["end_date"])

    context = printing_services.build_nozzle_ledger_context(nozzle, start_date, end_date)
    filename = f"nozzle-{nozzle.number}-ledger-{start_date}-{end_date}.pdf"
    return _render_pdf_response("printing/nozzle_ledger_print.html", context, filename)


@login_required
def all_nozzles_performance_print(request):
    year = int(request.GET["year"])
    month = int(request.GET["month"])
    if request.GET.get("tank_id"):
        tank = get_object_or_404(Tank.objects.select_related("product"), pk=int(request.GET["tank_id"]))
    else:                                    # same default as the screen: the first fuel (Regular)
        tank = Tank.objects.select_related("product").order_by("product__name").first()
        if tank is None:
            raise Http404("No tank configured.")

    context = printing_services.build_all_nozzles_performance_context(year, month, tank)
    filename = f"all-nozzles-{tank.product.name.lower()}-{year}-{month:02d}.pdf"
    return _render_pdf_response("printing/all_nozzles_performance_print.html", context, filename)


@login_required
def nozzle_monthly_print(request):
    year = int(request.GET["year"])
    month = int(request.GET["month"])

    context = printing_services.build_nozzle_monthly_context(year, month)
    filename = f"nozzle-monthly-{year}-{month:02d}.pdf"
    return _render_pdf_response("printing/nozzle_monthly_print.html", context, filename)


@login_required
def petroleum_ledger_print(request, tank_id):
    tank = Tank.objects.select_related("product").get(pk=tank_id)

    start_date = datetime.date.fromisoformat(request.GET["start_date"])
    end_date = datetime.date.fromisoformat(request.GET["end_date"])

    context = printing_services.build_petroleum_ledger_context(tank, start_date, end_date)
    filename = f"tank-{tank.product.name}-ledger-{start_date}-{end_date}.pdf"
    return _render_pdf_response("printing/petroleum_ledger_print.html", context, filename)


@login_required
def petroleum_monthly_print(request):
    year = int(request.GET["year"])
    month = int(request.GET["month"])

    context = printing_services.build_petroleum_monthly_context(year, month)
    filename = f"tank-monthly-{year}-{month:02d}.pdf"
    return _render_pdf_response("printing/petroleum_monthly_print.html", context, filename)


@login_required
def statement_print(request):
    year = int(request.GET["year"])
    month = int(request.GET["month"])

    context = printing_services.build_statement_context(year, month)
    filename = f"statement-{year}-{month:02d}.pdf"
    return _render_pdf_response("printing/statement_print.html", context, filename)


@login_required
def seals_print(request):
    start_date = datetime.date.fromisoformat(request.GET["start_date"])
    end_date = datetime.date.fromisoformat(request.GET["end_date"])

    context = printing_services.build_seals_context(start_date, end_date)
    filename = f"seals-{start_date}-{end_date}.pdf"
    return _render_pdf_response("printing/seals_print.html", context, filename)


@login_required
def comparison_print(request):
    year = int(request.GET["year"])
    month = int(request.GET["month"])

    context = printing_services.build_comparison_context(year, month)
    filename = f"comparison-{year}-{month:02d}.pdf"
    return _render_pdf_response("printing/comparison_print.html", context, filename)


@login_required
def sales_invoice_print(request, date):
    from apps.workday.models import DailyWorkingDay

    working_day = DailyWorkingDay.objects.get(date=datetime.date.fromisoformat(date))

    context = printing_services.build_sales_invoice_context(working_day)
    filename = f"sales-invoice-{date}.pdf"
    return _render_pdf_response("printing/sales_invoice_print.html", context, filename)


@login_required
def deposit_decade_print(request):
    year = int(request.GET["year"])
    month = int(request.GET["month"])
    decade = request.GET["decade"]

    context = printing_services.build_deposit_decade_context(year, month, decade)
    filename = f"deposits-{decade}-{year}-{month:02d}.pdf"
    return _render_pdf_response("printing/deposit_decade_print.html", context, filename)


@login_required
def purchases_ledger_print(request):
    start_date = datetime.date.fromisoformat(request.GET["start_date"])
    end_date = datetime.date.fromisoformat(request.GET["end_date"])

    context = printing_services.build_purchases_ledger_context(start_date, end_date)
    filename = f"purchases-{start_date}-{end_date}.pdf"
    return _render_pdf_response("printing/purchases_ledger_print.html", context, filename)
