"""
License system. Kept architecturally independent of accounting chronology
(see workday app): License.start_date fixes ONLY the 365-day license
period and records when the software was first activated -- it does NOT
define where accounting history begins (that's day 1 of the calendar
month containing start_date; see workday/services.py).

Renewal credential handling:
  - The renewal password is NEVER stored in plaintext anywhere in this
    project (source, templates, JS, fixtures, comments, logs, or this
    file).
  - Only a securely generated Django password hash (PBKDF2, via
    django.contrib.auth.hashers.make_password) is stored, in
    RENEWAL_PASSWORD_HASH below.
  - Verification uses django.contrib.auth.hashers.check_password(), which
    is constant-time and salted -- never a raw string comparison.
  - Renewing the license only ever updates License fields; it must never
    touch accounting data (sales, purchases, inventory, reports).
"""

from django.db import models
from django.utils import timezone


# Securely generated hash of the configured renewal password. The
# plaintext password itself is not present anywhere in the codebase --
# only this hash, produced once at build/setup time via
# django.contrib.auth.hashers.make_password(). To change the renewal
# password, generate a new hash the same way and replace this value; do
# not attempt to store or derive the plaintext from it.
RENEWAL_PASSWORD_HASH = (
    "pbkdf2_sha256$1000000$dQwCcyRD9pfE40dMoa4O64$"
    "/c5BQyi1cQQ9np6mP36OtHJMpxS1sNtkRYfCRS4gee0="
)


class License(models.Model):
    start_date = models.DateField(
        help_text="First activation date. Starts the license period AND "
                   "is renewed to 'today' on successful renewal. Does NOT "
                   "define accounting history start."
    )
    duration_days = models.PositiveIntegerField(default=365)

    class Meta:
        verbose_name = "License"
        verbose_name_plural = "Licenses"

    def __str__(self):
        return f"License from {self.start_date} ({self.duration_days} days)"

    @property
    def expiry_date(self):
        return self.start_date + timezone.timedelta(days=self.duration_days)

    def days_until_expiry(self, as_of=None):
        as_of = as_of or timezone.localdate()
        return (self.expiry_date - as_of).days

    def is_valid(self, as_of=None):
        return self.days_until_expiry(as_of) >= 0
