"""
Template context available on every page, not just views that explicitly
build it -- this is what makes the header's date selector and license
badge genuinely global instead of dashboard-only. Registered in
config/settings/base.py's TEMPLATES["OPTIONS"]["context_processors"].

Kept deliberately tiny: this only reads already-computed state from
workday/license services, never any accounting logic of its own.
"""

from apps.license import services as license_services
from apps.workday import services as workday_services


def global_header_context(request):
    if not request.user.is_authenticated:
        return {}

    lic = license_services.get_current_license()

    # Station name + address for the shared header: the same Station row
    # (and the same Persian display mapping) that the PDF headers use, so
    # the screen and the printed reports always show the same identity.
    from apps.printing.services import get_station_metadata

    station = get_station_metadata()
    location = "، ".join(part for part in (station["province"], station["city"]) if part)

    return {
        "station_display": {
            "name": station.get("short_name") or station["name"],
            "location": location,
        },
        "global_date": workday_services.get_global_date(request),
        "today": workday_services.get_today(),
        "license_valid": lic is not None and lic.is_valid(),
        "license_warning": license_services.should_show_expiry_warning(),
        "license_days_remaining": (
            license_services.days_until_expiry() if lic else None
        ),
    }
