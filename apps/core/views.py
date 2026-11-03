"""
Main dashboard. Aggregates just enough context from other apps' services
to render the two-column tank/nozzle layout and license status -- no
accounting logic lives here, only orchestration.
"""

import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from apps.license import services as license_services
from apps.stations.models import Tank, Nozzle
from apps.workday import services as workday_services


@login_required
def dashboard(request):
    tanks = Tank.objects.select_related("product").order_by("product__name")
    nozzles = Nozzle.objects.select_related("tank__product").order_by("number")

    lic = license_services.get_current_license()
    show_warning = license_services.should_show_expiry_warning()
    days_remaining = license_services.days_until_expiry() if lic else None

    next_required_date = workday_services.get_next_required_date()
    incomplete_count = len(workday_services.get_incomplete_days())

    context = {
        "tanks": tanks,
        "nozzles": nozzles,
        "license_valid": lic is not None and lic.is_valid(),
        "license_warning": show_warning,
        "license_days_remaining": days_remaining,
        "next_required_date": next_required_date,
        "incomplete_days_count": incomplete_count,
    }
    return render(request, "core/dashboard.html", context)


# Maps a page's app namespace to the URL name of that app's own
# top-level "show me this date" view, plus the args it needs beyond the
# date itself. Used by set_global_date below to send the operator to the
# equivalent page for the newly-picked date, instead of literally
# re-requesting the URL they were just on (which still has the OLD date
# baked into its path and would just show that same old date again).
_SECTION_DATE_VIEWS = {
    "sales": ("sales:invoice_detail", []),
    "inventory": ("inventory:day_detail", []),
}


@login_required
def set_global_date(request):
    """
    Target of the header's date-selector form (visible on every page via
    templates/base.html). Updates the session's global working date,
    then sends the operator to see that date reflected:

    - On sales/purchases/inventory's own date-scoped pages (invoice
      detail, nozzle entry, purchase entry/edit, tank inventory entry,
      etc.), those pages' URLs have the *old* date baked into the path
      itself (see each app's urls.py -- every one of these is
      "<str:date>/..."), so simply reloading "the same page" would just
      show that old date again with nothing actually changed. Instead
      this redirects to that section's own top-level date view
      (invoice_detail / day_detail) for the newly
      picked date -- record-specific sub-pages (editing one purchase
      invoice, one tank's opening entry, one nozzle's form) don't carry
      a sensible equivalent under a different date, so landing on the
      section's day overview is the correct, unsurprising result.
    - Everywhere else (the dashboard, each app's own choose_date screen,
      any future date-agnostic page), the old "return to the same page"
      behavior is exactly right, since that page already reads the
      session's global date on every load rather than a URL segment.

    Chronology (can_enter_date) is intentionally NOT enforced here: each
    target view already checks it and redirects to its own choose_date
    screen with an explanation if the date is out of scope, exactly as
    every other date entry point in the app already behaves.
    """
    if request.method == "POST":
        raw = request.POST.get("date", "")
        try:
            date = datetime.date.fromisoformat(raw)
        except ValueError:
            messages.error(request, "تاریخ واردشده معتبر نیست.")
            date = None
        else:
            workday_services.set_global_date(request, date)

        if date is not None:
            section = request.POST.get("section", "")
            view_name, extra_args = _SECTION_DATE_VIEWS.get(section, (None, None))
            if view_name:
                return HttpResponseRedirect(
                    reverse(view_name, args=[date.isoformat(), *extra_args])
                )

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("core:dashboard")
    return HttpResponseRedirect(next_url)
