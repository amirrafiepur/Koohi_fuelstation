from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.core.jalali import current_jalali_year_month
from apps.workday import services as workday_services

from . import services as statement_services
from .forms import DigitalSalesForm, TankerCapacityForm
from .models import StatementEntry


@login_required
def statement(request):
    """
    صورت وضعیت ماهانه main page. Behaves like گزارش ماهانه مخازن: the
    operator picks year/month and the page reloads via GET (no separate
    نمایش/Submit button) -- see templates/statement/statement.html.
    """
    today = workday_services.get_today()
    default_year, default_month = current_jalali_year_month(today)
    year = int(request.GET.get("year", default_year))
    month = int(request.GET.get("month", default_month))

    rows = statement_services.build_statement_rows(year, month)

    return render(
        request, "statement/statement.html",
        {"rows": rows, "year": year, "month": month},
    )


@login_required
def digital_sales_entry(request, entry_id):
    """
    "ورود فروش دیجیتال": a minimal form containing only فروش دیجیتال,
    opened from a button on the main statement page.
    """
    entry = get_object_or_404(StatementEntry, pk=entry_id)

    if request.method == "POST":
        form = DigitalSalesForm(request.POST, instance=entry)
        if form.is_valid():
            form.save()
            return redirect(
                f"{reverse('statement:statement')}?year={entry.year}&month={entry.month}"
            )
    else:
        form = DigitalSalesForm(instance=entry)

    return render(
        request, "statement/digital_sales_form.html",
        {"form": form, "entry": entry},
    )


@login_required
def tanker_capacity_entry(request, entry_id):
    """ظرفیت نفتکش: manually editable, independent of تعداد نفتکش."""
    entry = get_object_or_404(StatementEntry, pk=entry_id)

    if request.method == "POST":
        form = TankerCapacityForm(request.POST, instance=entry)
        if form.is_valid():
            form.save()

    return redirect(f"{reverse('statement:statement')}?year={entry.year}&month={entry.month}")
