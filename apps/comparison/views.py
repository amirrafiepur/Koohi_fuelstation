from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.core.jalali import current_jalali_year_month
from apps.workday import services as workday_services

from . import services as comparison_services
from .forms import DigitalEntryForm
from .models import DigitalEntry


@login_required
def comparison(request):
    """
    مقایسه سیستم مکانیکی و دیجیتال main page. Same auto-display behavior
    as صورت وضعیت ماهانه: the operator picks year/month and the page
    reloads via GET, no separate نمایش/Submit button.
    """
    today = workday_services.get_today()
    default_year, default_month = current_jalali_year_month(today)
    year = int(request.GET.get("year", default_year))
    month = int(request.GET.get("month", default_month))

    mechanical_rows = comparison_services.build_mechanical_rows(year, month)
    digital_rows = comparison_services.build_digital_rows(year, month)

    return render(
        request, "comparison/comparison.html",
        {
            "mechanical_rows": mechanical_rows,
            "digital_rows": digital_rows,
            "year": year,
            "month": month,
        },
    )


@login_required
def digital_entry_edit(request, entry_id):
    """Manual entry/edit form for one فروش دیجیتال row."""
    entry = get_object_or_404(DigitalEntry, pk=entry_id)

    if request.method == "POST":
        form = DigitalEntryForm(request.POST, instance=entry)
        if form.is_valid():
            form.save()
            return redirect(
                f"{reverse('comparison:comparison')}?year={entry.year}&month={entry.month}"
            )
    else:
        form = DigitalEntryForm(instance=entry)

    return render(
        request, "comparison/digital_entry_form.html",
        {"form": form, "entry": entry},
    )
