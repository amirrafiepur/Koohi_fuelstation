"""
Deposit views: add/edit/delete/list. Deposits are fully optional and have
no chronology dependency on DailyWorkingDay -- the date field defaults to
today at creation time (a sensible default, not a hard requirement) but
the operator can freely pick any historical date, and editing never
overwrites that original date/decade.
"""

import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.jalali import current_jalali_year_month, to_jalali
from apps.workday import services as workday_services

from . import services as deposit_services
from .forms import DepositForm
from .models import Deposit


def _decade_for_date(date: datetime.date) -> str:
    """
    Computed from the date, never stored/duplicated as separate truth
    -- but pre-filled here as a form convenience the operator can still
    override, since the model field itself is the source of truth once
    saved.

    The decade (1st/2nd/3rd) is a slice of the operator's JALALI month
    (Deposit.year/month are also Jalali -- see DepositForm), so the
    day-of-month used here must be the Jalali day, not the Gregorian
    one: a Gregorian day-of-month can land in a different third of the
    month than the corresponding Jalali day (e.g. Gregorian day 25 can
    fall in the Jalali month's first decade).
    """
    jalali_day = to_jalali(date).day
    if jalali_day <= 10:
        return Deposit.FIRST_DECADE
    elif jalali_day <= 20:
        return Deposit.SECOND_DECADE
    return Deposit.THIRD_DECADE


@login_required
def deposit_list(request):
    """
    واریزی‌ها landing page: a year/month selector (same JALALI
    year/month pattern as reports:petroleum_monthly) plus a 3-row
    دهه‌ اول/دوم/سوم summary table, each row's total reusing
    deposit_services.decade_totals() -- no per-decade sum computed here.
    """
    today = workday_services.get_today()
    default_year, default_month = current_jalali_year_month(today)
    year = int(request.GET.get("year", default_year))
    month = int(request.GET.get("month", default_month))

    rows = deposit_services.decade_totals(year, month)
    total = deposit_services.monthly_total(rows)

    return render(
        request, "deposits/deposit_list.html",
        {"rows": rows, "year": year, "month": month, "monthly_total": total},
    )


@login_required
def deposit_decade_detail(request, year, month, decade):
    """
    One decade's deposits, chronological, for the given JALALI
    year/month -- reuses deposit_services.deposits_in_decade() verbatim;
    no re-filtering or re-sorting logic here.
    """
    year = int(year)
    month = int(month)
    deposits = deposit_services.deposits_in_decade(year, month, decade)
    decade_labels = {
        Deposit.FIRST_DECADE: "دهه اول",
        Deposit.SECOND_DECADE: "دهه دوم",
        Deposit.THIRD_DECADE: "دهه سوم",
    }
    decade_label = decade_labels[decade]

    return render(
        request, "deposits/deposit_decade_detail.html",
        {
            "deposits": deposits, "year": year, "month": month,
            "decade": decade, "decade_label": decade_label,
            # "مجموع واریزی دهه": sum over exactly the deposits listed below.
            "decade_total": deposit_services.decade_total(year, month, decade),
        },
    )


@login_required
def deposit_create(request):
    if request.method == "POST":
        form = DepositForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "واریز ثبت شد.")
            return redirect("deposits:deposit_list")
    else:
        today = workday_services.get_today()
        today_jalali = to_jalali(today)
        form = DepositForm(initial={
            "date": today,
            # year/month are Jalali on this model (see DepositForm/
            # Deposit.year/month) -- default them from the operator's
            # current Jalali month, not the Gregorian one.
            "year": today_jalali.year,
            "month": today_jalali.month,
            "decade": _decade_for_date(today),
        })

    return render(request, "deposits/deposit_form.html", {"form": form, "editing": False})


@login_required
def deposit_edit(request, pk):
    """Editing preserves the original date -- the form never resets it,
    it only lets the operator correct the business fields."""
    deposit = get_object_or_404(Deposit, pk=pk)

    if request.method == "POST":
        form = DepositForm(request.POST, instance=deposit)
        if form.is_valid():
            form.save()
            messages.success(request, "واریز بروزرسانی شد.")
            return redirect("deposits:deposit_list")
    else:
        form = DepositForm(instance=deposit)

    return render(request, "deposits/deposit_form.html", {"form": form, "editing": True, "deposit": deposit})


@login_required
def deposit_delete(request, pk):
    """Destructive; requires strong confirmation, per the project-wide
    deletion rule."""
    deposit = get_object_or_404(Deposit, pk=pk)

    if request.method == "POST":
        deposit.delete()
        messages.success(request, "واریز حذف شد.")
        return redirect("deposits:deposit_list")

    return render(request, "deposits/deposit_confirm_delete.html", {"deposit": deposit})
