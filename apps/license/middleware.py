"""
Enforces license validity on every request except the license/renewal page
itself (exempted to avoid a redirect loop) and static assets. Enforced at
the middleware level -- not only in the PySide6 shell -- because that
can't be bypassed by talking to the local Django server directly.
"""

from django.shortcuts import redirect
from django.urls import resolve, reverse, Resolver404

from . import services

# Paths that must remain reachable even when the license is expired.
EXEMPT_URL_NAMES = {
    "license:renew",
    "accounts:login",
    "accounts:first_setup",
    "accounts:forgot_password",
    "accounts:reset_password",
}


class LicenseEnforcementMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # request.resolver_match is not yet populated during the request
        # phase of middleware (it's set later, during view dispatch), so
        # resolve the path ourselves rather than relying on it here.
        try:
            match = resolve(request.path_info)
            url_name = (
                f"{match.namespace}:{match.url_name}" if match.namespace else match.url_name
            )
        except Resolver404:
            url_name = None

        is_static = request.path.startswith("/static/")

        if url_name not in EXEMPT_URL_NAMES and not is_static:
            if not services.is_license_valid():
                return redirect(reverse("license:renew"))

        return self.get_response(request)
