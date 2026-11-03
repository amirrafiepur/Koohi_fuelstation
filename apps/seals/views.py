"""
Seal views: add/edit/delete/list. NozzleSeal has no chronology dependency
(it's event-based, not a daily working-day record) for add/edit/delete --
those don't touch workday/services.py at all, unlike sales/purchases/
inventory. seal_list's date-range filtering (below) uses
workday_services.get_global_date() only to seed its DEFAULT range; it
does not gate entry the way sales/purchases do.
"""

import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.workday import services as workday_services

from . import services as seal_services
from .forms import NozzleSealForm
from .models import NozzleSeal


@login_required
def seal_list(request):
    """
    پلمپ‌ها date-range list, mirroring دفتر موجودی و عملیات's UI/workflow
    (date-range inputs that auto-navigate on change, no submit button,
    plus a print button) -- see templates/seals/seal_list.html and
    templates/reports/petroleum_inventory_ledger.html. Default range is
    the operator's current global Date Control date (both ends), per the
    explicit requirement -- NOT the ledger's own "current Jalali month"
    default.
    """
    default_date = workday_services.get_global_date(request)
    start_date = default_date
    end_date = default_date

    if request.GET.get("start_date"):
        start_date = datetime.date.fromisoformat(request.GET.get("start_date"))
    if request.GET.get("end_date"):
        end_date = datetime.date.fromisoformat(request.GET.get("end_date"))

    # Same query as the PDF (apps/seals/services.py): by nozzle number, then newest first.
    seals = seal_services.seals_in_range(start_date, end_date)

    return render(
        request, "seals/seal_list.html",
        {"seals": seals, "start_date": start_date, "end_date": end_date},
    )


@login_required
def seal_create(request):
    if request.method == "POST":
        form = NozzleSealForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "پلمپ ثبت شد.")
            return redirect("seals:seal_list")
    else:
        form = NozzleSealForm()

    return render(request, "seals/seal_form.html", {"form": form, "editing": False})


@login_required
def seal_edit(request, pk):
    seal = get_object_or_404(NozzleSeal, pk=pk)

    if request.method == "POST":
        form = NozzleSealForm(request.POST, instance=seal)
        if form.is_valid():
            form.save()
            messages.success(request, "پلمپ بروزرسانی شد.")
            return redirect("seals:seal_list")
    else:
        form = NozzleSealForm(instance=seal)

    return render(request, "seals/seal_form.html", {"form": form, "editing": True, "seal": seal})


@login_required
def seal_delete(request, pk):
    """
    Deletion is destructive and requires strong confirmation, per the
    project-wide editing/deletion rule -- this view only deletes on POST,
    never on GET, and the template requires an explicit confirm click.
    """
    seal = get_object_or_404(NozzleSeal, pk=pk)

    if request.method == "POST":
        seal.delete()
        messages.success(request, "پلمپ حذف شد.")
        return redirect("seals:seal_list")

    return render(request, "seals/seal_confirm_delete.html", {"seal": seal})
