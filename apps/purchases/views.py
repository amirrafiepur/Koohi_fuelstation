"""
Purchase views: choosing a working date (reuses the same chronology rules
as sales -- rule 10) to enter a purchase for a tank/product (rule 1: any
number of these per day), plus a date-range purchase list -- two separate
tables, Regular and Super -- with a combined print button, mirroring the
Nozzle Performance and Petroleum Ledger report sections' UI/workflow.

No business math lives here -- only orchestration of purchases/services.py
and workday/services.py, per rule 9.
"""

import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.jalali import current_jalali_year_month, jalali_month_bounds
from apps.sales.forms import WorkingDateForm
from apps.stations.models import Tank
from apps.workday import services as workday_services
from apps.workday.models import DailyWorkingDay

from . import services as purchase_services
from .forms import PurchaseInvoiceForm
from .models import PurchaseInvoice


def _parse_date(date_str: str) -> datetime.date:
    return datetime.date.fromisoformat(date_str)


@login_required
def choose_working_date(request):
    """
    Lets the operator enter a purchase for a day other than their current
    global date (the date-range list's own "+ فاکتور جدید" buttons skip
    straight to purchase_entry for the current global date -- this page
    is for picking a different one). Purchases obey the same chronology
    system as sales (rule 10) -- this deliberately reuses
    workday_services.can_enter_date() rather than introducing a separate
    date system, and reuses sales' WorkingDateForm since the shape is
    identical (a single date field). Prefers the operator's global
    working date over the chronology default so switching sections
    doesn't reset it -- see workday_services.get_global_date().
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
                return redirect("purchases:invoice_list")
    else:
        form = WorkingDateForm(initial=initial)

    context = {
        "form": form,
        "next_required_date": next_required,
        "incomplete_days": workday_services.get_incomplete_days(),
    }
    return render(request, "purchases/choose_date.html", context)


@login_required
def invoice_list(request):
    """
    Purchases section landing page ("خرید" in the nav): a date range
    (defaulting to the current Jalali month through today, exactly like
    reports:nozzle_ledger/petroleum_ledger) showing every PurchaseInvoice
    in that range, as two separate tables -- one per product (rule 1: any
    number of invoices per day; rule 7's daily total is not shown here
    since the range can span many days, but every row's own total_amount
    is the model's existing property, unchanged).

    Regular/Super stay two independent tables, one per Tank, exactly as
    before -- this view does not merge or reinterpret that separation,
    only replaces the single-day window with a date range.
    """
    today = workday_services.get_today()
    jalali_year, jalali_month = current_jalali_year_month(today)
    start_date, _ = jalali_month_bounds(jalali_year, jalali_month)
    end_date = today

    if request.GET.get("start_date"):
        start_date = datetime.date.fromisoformat(request.GET.get("start_date"))
    if request.GET.get("end_date"):
        end_date = datetime.date.fromisoformat(request.GET.get("end_date"))

    tanks = Tank.objects.select_related("product").order_by("product__name")
    tank_rows = [
        {
            "tank": tank,
            "invoices": purchase_services.get_purchase_invoices_in_range(tank, start_date, end_date),
        }
        for tank in tanks
    ]

    return render(
        request, "purchases/invoice_list.html",
        {
            "tank_rows": tank_rows,
            "start_date": start_date,
            "end_date": end_date,
            "new_entry_date": workday_services.get_global_date(request),
        },
    )


@login_required
def purchase_entry(request, date, tank_id):
    """
    Creates a new PurchaseInvoice for this tank/day. Never edits/replaces
    an existing one implicitly -- each unloading event is its own record
    (rule 1), so this view only ever adds; editing a specific invoice is a
    separate view (purchase_edit) that never changes its working_day.
    """
    working_day, _ = DailyWorkingDay.objects.get_or_create(date=_parse_date(date))
    allowed, reason = workday_services.can_enter_date(working_day.date)
    if not allowed:
        messages.error(request, reason)
        return redirect("purchases:choose_date")

    tank = get_object_or_404(Tank, pk=tank_id)

    # Rate suggestion: most recently used rate for this PRODUCT (via this
    # tank, since each tank has exactly one product) -- rules 5 and 6.
    # Regular and Super are naturally independent here because each is a
    # separate Tank row; nothing shares a rate across products.
    suggested_rate = purchase_services.get_most_recent_rate(tank)
    initial = {"purchase_rate": suggested_rate} if suggested_rate is not None else {}

    if request.method == "POST":
        form = PurchaseInvoiceForm(request.POST)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.working_day = working_day
            invoice.tank = tank
            invoice.save()
            messages.success(request, "فاکتور خرید ثبت شد.")
            return redirect("purchases:invoice_list")
    else:
        form = PurchaseInvoiceForm(initial=initial)

    return render(
        request, "purchases/purchase_entry.html",
        {"form": form, "working_day": working_day, "tank": tank},
    )


@login_required
def purchase_edit(request, date, pk):
    """
    Edits an existing PurchaseInvoice. Its working_day and original
    entry are never reassigned here -- only the editable business fields
    change, consistent with the project-wide editing rule that a
    record's original working date is never altered by an edit.
    """
    working_day, _ = DailyWorkingDay.objects.get_or_create(date=_parse_date(date))
    invoice = get_object_or_404(PurchaseInvoice, pk=pk, working_day=working_day)

    allowed, reason = workday_services.can_enter_date(working_day.date)
    if not allowed:
        messages.error(request, reason)
        return redirect("purchases:choose_date")

    if request.method == "POST":
        form = PurchaseInvoiceForm(request.POST, instance=invoice)
        if form.is_valid():
            form.save()
            messages.success(request, "فاکتور خرید بروزرسانی شد.")
            return redirect("purchases:invoice_list")
    else:
        form = PurchaseInvoiceForm(instance=invoice)

    return render(
        request, "purchases/purchase_entry.html",
        {"form": form, "working_day": working_day, "tank": invoice.tank, "editing": True},
    )


@login_required
def purchase_delete(request, date, pk):
    """
    Deletes a PurchaseInvoice. Mirrors apps/seals/views.py:seal_delete --
    the project-wide deletion pattern: only ever deletes on POST (an
    explicit confirm-page click), never on GET, so a GET here always
    just shows the confirmation page without making any change.
    """
    working_day, _ = DailyWorkingDay.objects.get_or_create(date=_parse_date(date))
    invoice = get_object_or_404(PurchaseInvoice, pk=pk, working_day=working_day)

    if request.method == "POST":
        invoice.delete()
        messages.success(request, "فاکتور خرید حذف شد.")
        return redirect("purchases:invoice_list")

    return render(request, "purchases/purchase_confirm_delete.html", {"invoice": invoice})
