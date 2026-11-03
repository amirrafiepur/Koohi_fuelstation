"""
Inventory views: opening-inventory setup for day 1 of the first accounting
month, daily actual-inventory entry per tank, and a tank inventory list/
detail showing the full derived breakdown (Total/Theoretical Inventory,
Shortage, Overage) for a working day.

No business math lives here -- only orchestration of inventory/services.py
and workday/services.py, exactly as in sales/purchases.
"""

import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.sales.forms import WorkingDateForm
from apps.stations.models import Tank
from apps.workday import services as workday_services
from apps.workday.models import DailyWorkingDay

from . import services as inventory_services
from .forms import OpeningInventoryForm, ActualInventoryForm
from .models import TankInventory, OpeningInventory


def _parse_date(date_str: str) -> datetime.date:
    return datetime.date.fromisoformat(date_str)


@login_required
def choose_working_date(request):
    """Entry point for "مخازن" in the nav. Same chronology reuse as sales
    and purchases -- no separate date system. Prefers the operator's
    global working date over the chronology default so switching
    sections doesn't reset it -- see workday_services.get_global_date()."""
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
                return redirect("inventory:day_detail", date=date.isoformat())
    else:
        form = WorkingDateForm(initial=initial)

    context = {
        "form": form,
        "next_required_date": next_required,
        "incomplete_days": workday_services.get_incomplete_days(),
    }
    return render(request, "inventory/choose_date.html", context)


@login_required
def day_detail(request, date):
    """
    Shows every tank's inventory status for this working day: the
    manually-entered Actual Inventory (or a prompt to enter it if
    missing) plus the full derived breakdown once it exists. Actual
    Inventory is required every working day for every tank -- if
    missing, the day cannot be considered complete (enforced in
    workday completion checks, not here).

    For day 1 of the first accounting month and any tank with no
    OpeningInventory row yet, this view also prompts for the opening
    balance (0 by default) before the actual-inventory entry can
    meaningfully be interpreted.
    """
    working_day, _ = DailyWorkingDay.objects.get_or_create(date=_parse_date(date))
    allowed, reason = workday_services.can_enter_date(working_day.date)
    if not allowed:
        messages.error(request, reason)
        return redirect("inventory:choose_date")

    workday_services.set_global_date(request, working_day.date)

    accounting_start = workday_services.get_accounting_start_date()
    is_first_accounting_month_day1 = (
        accounting_start is not None and working_day.date == accounting_start
    )

    tanks = Tank.objects.select_related("product").order_by("product__name")
    rows = []
    for tank in tanks:
        inventory_row = TankInventory.objects.filter(tank=tank, working_day=working_day).first()

        needs_opening_inventory = (
            is_first_accounting_month_day1
            and not OpeningInventory.objects.filter(tank=tank, effective_month=accounting_start).exists()
        )

        breakdown = None
        if inventory_row is not None and not needs_opening_inventory:
            try:
                total, theoretical, shortage, overage = inventory_services.compute_tank_inventory(
                    tank, working_day
                )
                breakdown = {
                    "total_inventory": total,
                    "theoretical_inventory": theoretical,
                    "shortage": shortage,
                    "overage": overage,
                }
            except ValueError:
                breakdown = None

        rows.append({
            "tank": tank,
            "inventory_row": inventory_row,
            "needs_opening_inventory": needs_opening_inventory,
            "breakdown": breakdown,
        })

    return render(
        request, "inventory/day_detail.html",
        {"working_day": working_day, "rows": rows, "accounting_start": accounting_start},
    )


@login_required
def opening_inventory_entry(request, date, tank_id):
    """
    Prompts for the opening balance for day 1 of the first accounting
    month, per architecture doc "Opening Inventory Rule": default 0
    unless the operator has a real value from their existing paper
    ledger. Never forces a non-zero value.
    """
    working_day, _ = DailyWorkingDay.objects.get_or_create(date=_parse_date(date))
    tank = get_object_or_404(Tank, pk=tank_id)
    accounting_start = workday_services.get_accounting_start_date()

    if accounting_start is None or working_day.date != accounting_start:
        messages.error(request, "این فرم فقط برای روز اول ماه حسابداری اول قابل استفاده است.")
        return redirect("inventory:day_detail", date=date)

    existing = OpeningInventory.objects.filter(tank=tank, effective_month=accounting_start).first()

    if request.method == "POST":
        form = OpeningInventoryForm(request.POST, instance=existing)
        if form.is_valid():
            opening = form.save(commit=False)
            opening.tank = tank
            opening.effective_month = accounting_start
            opening.save()
            messages.success(request, "موجودی افتتاحیه ثبت شد.")
            return redirect("inventory:day_detail", date=date)
    else:
        form = OpeningInventoryForm(instance=existing, initial={} if existing else {"opening_quantity": 0})

    return render(
        request, "inventory/opening_inventory_entry.html",
        {"form": form, "working_day": working_day, "tank": tank},
    )


@login_required
def actual_inventory_entry(request, date, tank_id):
    """
    Entry/edit of the one manually-entered field: Actual Inventory.
    Everything else (Previous Balance, Daily Purchase, Test Return, Total
    Inventory, Daily Sales, Theoretical Inventory) is computed via the
    existing inventory/services.py functions and only ever displayed
    read-only alongside the form -- never entered here, and never
    recomputed with different logic than the rest of the app already
    uses (day_detail, printing, reports all call these same functions).

    These derived values do not depend on this day's own Actual
    Inventory (only Shortage/Overage do, which this form does not show),
    so they are safe to compute and display even before Actual Inventory
    has ever been entered for this tank/day -- unlike
    compute_tank_inventory(), which requires a TankInventory row to
    already exist and would raise ValueError on a brand-new entry.
    """
    working_day, _ = DailyWorkingDay.objects.get_or_create(date=_parse_date(date))
    allowed, reason = workday_services.can_enter_date(working_day.date)
    if not allowed:
        messages.error(request, reason)
        return redirect("inventory:choose_date")

    tank = get_object_or_404(Tank, pk=tank_id)
    existing = TankInventory.objects.filter(tank=tank, working_day=working_day).first()

    previous_balance, previous_overage = inventory_services.get_previous_balance_and_overage(
        tank, working_day
    )
    daily_purchase = inventory_services.get_daily_purchase_total(tank, working_day)
    test_return = inventory_services.get_test_return(tank, working_day)
    daily_sales = inventory_services.get_daily_sales(tank, working_day)
    total_inventory = previous_balance + daily_purchase + test_return + previous_overage
    theoretical_inventory = inventory_services.compute_theoretical_inventory(
        total_inventory, daily_sales, test_return
    )

    if request.method == "POST":
        form = ActualInventoryForm(request.POST, instance=existing)
        if form.is_valid():
            row = form.save(commit=False)
            row.tank = tank
            row.working_day = working_day
            row.save()
            messages.success(request, "موجودی واقعی ثبت شد.")
            return redirect("inventory:day_detail", date=date)
    else:
        form = ActualInventoryForm(instance=existing)

    return render(
        request, "inventory/actual_inventory_entry.html",
        {
            "form": form, "working_day": working_day, "tank": tank,
            "previous_balance": previous_balance,
            "daily_purchase": daily_purchase,
            "test_return": test_return,
            "total_inventory": total_inventory,
            "daily_sales": daily_sales,
            "theoretical_inventory": theoretical_inventory,
        },
    )
