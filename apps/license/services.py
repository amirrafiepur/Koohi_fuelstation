"""
license/services.py -- business logic for license validity and renewal.
Other apps must depend only on is_license_valid()/days_until_expiry(),
never on License model internals or the renewal mechanism directly, so the
renewal mechanism can be swapped later without rewriting callers.
"""

from django.contrib.auth.hashers import check_password
from django.utils import timezone

from .models import License, RENEWAL_PASSWORD_HASH


def get_current_license():
    """There is only ever one License row for this single-station app."""
    return License.objects.order_by("-id").first()


def is_license_valid(as_of=None) -> bool:
    lic = get_current_license()
    if lic is None:
        return False
    return lic.is_valid(as_of)


def days_until_expiry(as_of=None):
    lic = get_current_license()
    if lic is None:
        return None
    return lic.days_until_expiry(as_of)


def should_show_expiry_warning(as_of=None, threshold_days: int = 7) -> bool:
    """True when the license is still valid but expires within
    threshold_days (inclusive)."""
    lic = get_current_license()
    if lic is None or not lic.is_valid(as_of):
        return False
    remaining = lic.days_until_expiry(as_of)
    return 0 <= remaining <= threshold_days


def activate_license(duration_days: int = 365, as_of=None) -> License:
    """Create the initial license exactly once during first-run setup.

    Existing licenses are never reset by this function. This guarantees that
    normal application startup or repeated setup calls cannot restart the
    365-day period.
    """
    existing = get_current_license()
    if existing is not None:
        return existing
    as_of = as_of or timezone.localdate()
    return License.objects.create(start_date=as_of, duration_days=duration_days)


def verify_renewal_password(candidate: str) -> bool:
    """Constant-time, salted verification against the stored hash. The
    plaintext password is never compared directly and never logged."""
    return check_password(candidate, RENEWAL_PASSWORD_HASH)


def renew_license(candidate_password: str, as_of=None) -> bool:
    """
    On correct password: start a new duration_days period from `as_of`
    (today), on the existing License row. Accounting data is never
    touched here -- only License.start_date changes.

    Returns True if renewal succeeded, False if the password was wrong.
    """
    if not verify_renewal_password(candidate_password):
        return False

    lic = get_current_license()
    as_of = as_of or timezone.localdate()
    if lic is None:
        # Initial activation belongs exclusively to first-run account setup.
        # Renewal must never silently create or activate a license.
        return False

    lic.start_date = as_of
    lic.save(update_fields=["start_date"])
    return True
