"""
License renewal view. This is the one page the LicenseEnforcementMiddleware
explicitly exempts (see middleware.py) so an expired license never causes a
redirect loop. Renewal only ever updates the License row -- never
accounting data (see services.renew_license docstring).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from . import services
from .forms import LicenseRenewalForm


@login_required
def renew(request):
    lic = services.get_current_license()
    already_valid = lic is not None and lic.is_valid()

    if request.method == "POST":
        form = LicenseRenewalForm(request.POST)
        if form.is_valid():
            success = services.renew_license(form.cleaned_data["password"])
            if success:
                messages.success(request, "لایسنس با موفقیت تمدید شد.")
                return redirect("core:dashboard")
            else:
                form.add_error("password", "رمز تمدید نادرست است.")
    else:
        form = LicenseRenewalForm()

    context = {
        "form": form,
        "already_valid": already_valid,
        "days_remaining": lic.days_until_expiry() if lic else None,
    }
    return render(request, "license/renew.html", context)
