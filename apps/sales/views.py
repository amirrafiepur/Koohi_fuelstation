"""
Sales views: choosing a working date, sequential per-nozzle entry (starts
at the first unregistered nozzle, auto-advances after save -- see
architecture doc §"Nozzle Entry UX"), the daily invoice detail (inspect
every nozzle separately), and the invoice list.

Business math never appears here -- only orchestration of
sales/services.py and workday/services.py.
"""

import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.stations.models import Nozzle
from apps.workday import services as workday_services
from apps.workday.models import DailyWorkingDay

from . import services as sales_services
from .forms import WorkingDateForm, NozzleSaleForm
from .models import SalesInvoice, NozzleSale


def _parse_date(date_str: str) -> datetime.date:
    """URL path converters pass dates as strings; every date-typed field
    downstream (DailyWorkingDay.date, comparisons in workday/services.py)
    expects an actual datetime.date, so parse once at the view boundary."""
    return datetime.date.fromisoformat(date_str)


@login_required
def choose_working_date(request):
    """
    Entry point for "فروش" in the nav. Prefers the operator's current
    global working date (set via the header selector) over the
    chronology default, so switching sections doesn't silently reset
    whatever date they were just looking at; falls back to the next
    required date if no global date has been set yet this session.
    """
    next_required = workday_services.get_next_required_date()
    initial = {"date": workday_services.get_global_date(request)}

    if request.method == "POST":
        form = WorkingDateForm(request.POST)
        if form.is_valid():
            date = form.cleaned_data["date"]
            allowed, reason = workday_services.can_enter_date(date)
            if not allowed:
                form.add_error("date", reason)
            else:
                workday_services.set_global_date(request, date)
                return redirect(reverse("sales:invoice_detail", args=[date.isoformat()]))
    else:
        form = WorkingDateForm(initial=initial)

    context = {
        "form": form,
        "next_required_date": next_required,
        "incomplete_days": workday_services.get_incomplete_days(),
    }
    return render(request, "sales/choose_date.html", context)


@login_required
def invoice_detail(request, date):
    """
    The daily sales invoice: shows aggregated totals plus every individual
    NozzleSale for inspection, per architecture doc §"Sales Invoice
    Architecture" -- opening a day must let the operator see each nozzle
    separately, not just the summary.
    """
    working_day, _ = DailyWorkingDay.objects.get_or_create(date=_parse_date(date))

    allowed, reason = workday_services.can_enter_date(working_day.date)
    if not allowed:
        messages.error(request, reason)
        return redirect("sales:choose_date")

    workday_services.set_global_date(request, working_day.date)

    invoice = SalesInvoice.objects.filter(working_day=working_day).first()
    nozzle_sales = (
        invoice.nozzle_sales.select_related("nozzle", "nozzle__tank__product").order_by("nozzle__number")
        if invoice
        else NozzleSale.objects.none()
    )

    all_registered, missing_numbers = sales_services.validate_all_nozzles_registered(working_day)
    totals = sales_services.get_daily_totals(working_day)

    context = {
        "working_day": working_day,
        "invoice": invoice,
        "nozzle_sales": nozzle_sales,
        "all_registered": all_registered,
        "missing_numbers": missing_numbers,
        "totals": totals,
    }
    return render(request, "sales/invoice_detail.html", context)


@login_required
def nozzle_entry(request, date, nozzle_number=None):
    """
    Sequential entry: if nozzle_number is omitted, redirects to the first
    unregistered nozzle for this working day. F2 (bound client-side) POSTs
    this same view; on save it redirects to the next unregistered nozzle,
    or back to the invoice detail once every nozzle is registered.
    """
    working_day, _ = DailyWorkingDay.objects.get_or_create(date=_parse_date(date))
    allowed, reason = workday_services.can_enter_date(working_day.date)
    if not allowed:
        messages.error(request, reason)
        return redirect("sales:choose_date")

    workday_services.set_global_date(request, working_day.date)

    all_registered, missing_numbers = sales_services.validate_all_nozzles_registered(working_day)

    if nozzle_number is None:
        if missing_numbers:
            return redirect("sales:nozzle_entry", date=date, nozzle_number=missing_numbers[0])
        return redirect("sales:invoice_detail", date=date)

    nozzle = get_object_or_404(Nozzle, number=nozzle_number)

    invoice = sales_services.get_or_create_sales_invoice(working_day, request.user)
    existing = NozzleSale.objects.filter(sales_invoice=invoice, nozzle=nozzle).first()

    suggested_rate = sales_services.get_most_recent_rate(nozzle.tank)
    suggested_previous_meter = sales_services.get_previous_new_meter(nozzle)
    initial = {}
    if existing is None and suggested_rate is not None:
        initial["sales_rate"] = suggested_rate
    if existing is None and suggested_previous_meter is not None:
        initial["previous_meter"] = suggested_previous_meter

    confirm_negative = request.POST.get("confirm_negative_meter") == "1"

    if request.method == "POST":
        form = NozzleSaleForm(request.POST, instance=existing)
        if form.is_valid():
            if form.has_negative_meter_movement() and not confirm_negative:
                # Non-blocking warning: re-render with the warning instead
                # of saving. The template resubmits with
                # confirm_negative_meter=1 once the operator confirms.
                context = {
                    "form": form, "working_day": working_day, "nozzle": nozzle,
                    "missing_numbers": missing_numbers, "show_negative_warning": True,
                }
                return render(request, "sales/nozzle_entry.html", context)

            nozzle_sale = form.save(commit=False)
            nozzle_sale.sales_invoice = invoice
            nozzle_sale.nozzle = nozzle
            nozzle_sale.save()

            _, still_missing = sales_services.validate_all_nozzles_registered(working_day)
            if still_missing:
                return redirect("sales:nozzle_entry", date=date, nozzle_number=still_missing[0])
            # All 26 nozzles are now registered for this day -- this is
            # the one and only completion requirement for فاکتور فروش
            # (see workday/services.py:get_incomplete_days, which treats
            # this condition as complete regardless of this call too;
            # closing the day here keeps DailyWorkingDay.status accurate
            # for any other reader of it).
            workday_services.close_day(working_day.date)
            messages.success(request, "تمام نازل‌های الزامی برای این روز ثبت شدند.")
            return redirect("sales:invoice_detail", date=date)
    else:
        form = NozzleSaleForm(instance=existing, initial=initial)

    context = {
        "form": form, "working_day": working_day, "nozzle": nozzle,
        "missing_numbers": missing_numbers, "show_negative_warning": False,
    }
    return render(request, "sales/nozzle_entry.html", context)


@login_required
def invoice_list(request):
    """Sales invoice list -- one row per working day with derived daily
    totals, per architecture doc §"Sales Invoice System"."""
    working_days = DailyWorkingDay.objects.filter(
        sales_invoice__isnull=False
    ).order_by("-date")

    rows = []
    for wd in working_days:
        totals = sales_services.get_daily_totals(wd)
        rows.append({"working_day": wd, "invoice": wd.sales_invoice, **totals})

    return render(request, "sales/invoice_list.html", {"rows": rows})
