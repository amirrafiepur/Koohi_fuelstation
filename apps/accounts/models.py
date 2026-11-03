"""
Operator extends Django's built-in User (authentication is Django's own
built-in system -- not custom) purely to identify which User is an
operator of this station. The actual "last used username" for login-field
prefill is a single global value (not per-user), stored on
apps.core.models.AppConfig, since it must reflect whichever operator most
recently logged in across the whole application.

Password recovery ("forgot password"):
  - Set once at account creation, alongside the password itself, as a
    security question and answer.
  - The question (security_question) is plain text -- it is meant to be
    shown back to the operator, so there is nothing to hide there.
  - The answer is NEVER stored in plaintext: security_answer_hash holds
    only a salted Django password hash (via
    django.contrib.auth.hashers.make_password), verified with
    check_password(), exactly like the license renewal password
    elsewhere in this project (see apps/license/models.py).

راه‌اندازی اولیه setup-password credential handling (SETUP_PASSWORD_HASH
below), mirroring apps/license/models.py's RENEWAL_PASSWORD_HASH exactly:
  - The setup password is NEVER stored in plaintext anywhere in this
    project (source, templates, JS, fixtures, comments, logs, or this
    file).
  - Only a securely generated Django password hash (PBKDF2, via
    django.contrib.auth.hashers.make_password) is stored below.
  - Verification uses django.contrib.auth.hashers.check_password(),
    which is constant-time and salted -- never a raw string comparison.
  - This is a SEPARATE credential from the license renewal password
    (apps/license/models.py:RENEWAL_PASSWORD_HASH) -- the two are
    unrelated and this one never touches the license app.
"""

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models


# Securely generated hash of the configured راه‌اندازی اولیه setup
# password. The plaintext password itself is not present anywhere in
# the codebase -- only this hash, produced once via
# django.contrib.auth.hashers.make_password(). To change the setup
# password, generate a new hash the same way and replace this value; do
# not attempt to store or derive the plaintext from it.
SETUP_PASSWORD_HASH = (
    "pbkdf2_sha256$1000000$3bLl05O2rWw6owAQLHef5w$"
    "BoRymzpg/OolbRTMc4xFKn/bwSDZQbDoe31Dx6dzU+k="
)


def verify_setup_password(candidate: str) -> bool:
    """Constant-time, salted verification against SETUP_PASSWORD_HASH.
    The plaintext password is never compared directly and never
    logged."""
    return check_password(candidate, SETUP_PASSWORD_HASH)


class Operator(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="operator_profile"
    )
    security_question = models.CharField(max_length=255)
    security_answer_hash = models.CharField(max_length=255)

    class Meta:
        verbose_name = "Operator"
        verbose_name_plural = "Operators"

    def __str__(self):
        return self.user.get_username()

    def set_security_answer(self, raw_answer: str) -> None:
        """Hashes and stores the answer -- the plaintext is never kept."""
        self.security_answer_hash = make_password(raw_answer)

    def check_security_answer(self, candidate: str) -> bool:
        """Constant-time, salted verification against the stored hash."""
        return check_password(candidate, self.security_answer_hash)
