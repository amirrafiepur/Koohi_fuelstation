"""Single-operator authentication and first-run account activation, plus
password recovery via a security question (see Operator model)."""

from django.contrib.auth import get_user_model, login as auth_login
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.shortcuts import redirect, render

from apps.core.models import AppConfig
from apps.license import services as license_services
from .forms import (
    FirstOperatorSetupForm,
    OperatorLoginForm,
    OperatorSetPasswordForm,
    SecurityAnswerForm,
)
from .models import Operator, verify_setup_password

# After this many incorrect راه‌اندازی اولیه setup-password attempts, the
# setup process is permanently locked for this installation (see
# first_operator_setup below and AppConfig.setup_failed_attempts/
# setup_locked, which persist the count so a restart can't reset it).
MAX_SETUP_PASSWORD_ATTEMPTS = 10


User = get_user_model()

# Session key set only after a correct security-answer check, and only
# ever consumed by reset_password -- this is what makes reset_password
# unreachable by guessing the URL without first passing the security
# question.
RECOVERY_VERIFIED_SESSION_KEY = "password_recovery_verified"


class OperatorLoginView(LoginView):
    template_name = "accounts/login.html"
    form_class = OperatorLoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["first_run"] = first_run_required()
        return context

    def get_initial(self):
        initial = super().get_initial()
        config = AppConfig.get_solo()
        if config.last_logged_in_username:
            initial["username"] = config.last_logged_in_username
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        config = AppConfig.get_solo()
        config.last_logged_in_username = form.get_user().get_username()
        config.save(update_fields=["last_logged_in_username"])
        return response


def first_run_required() -> bool:
    """A fresh installation is identified by having no Django User rows."""
    return not User.objects.exists()


def first_operator_setup(request):
    """
    Create the only operator on a fresh installation.

    Gated by a separate راه‌اندازی اولیه setup password (see
    apps/accounts/models.py:verify_setup_password -- a distinct
    credential from the license renewal password in apps/license/, never
    touched here): the account is created only once the correct setup
    password is supplied alongside valid account fields. Each incorrect
    setup-password attempt is counted on AppConfig (persisted in the
    database, so a restart cannot reset it); after
    MAX_SETUP_PASSWORD_ATTEMPTS wrong attempts, setup is permanently
    locked and this view refuses to render the form again, for this
    installation, forever.

    The first successful account creation atomically creates the Operator
    profile (with its security question/answer for later password
    recovery) and starts the 365-day license. Once any User exists, this
    route is permanently unavailable for that installation (the
    first_run_required() check above the lock check, unaffected by it).
    """
    if not first_run_required():
        return redirect("accounts:login")

    config = AppConfig.get_solo()
    if config.setup_locked:
        return render(request, "accounts/first_setup.html", {"locked": True})

    if request.method == "POST":
        form = FirstOperatorSetupForm(request.POST)
        setup_password_candidate = request.POST.get("setup_password", "")

        if not verify_setup_password(setup_password_candidate):
            config.setup_failed_attempts += 1
            if config.setup_failed_attempts >= MAX_SETUP_PASSWORD_ATTEMPTS:
                config.setup_locked = True
            config.save(update_fields=["setup_failed_attempts", "setup_locked"])

            if config.setup_locked:
                return render(request, "accounts/first_setup.html", {"locked": True})

            form.is_valid()  # populate cleaned_data/errors for the other fields too
            form.add_error("setup_password", "رمز راه‌اندازی نادرست است.")
        elif form.is_valid():
            with transaction.atomic():
                user = form.save()
                operator = Operator(
                    user=user,
                    security_question=form.cleaned_data["security_question"],
                )
                operator.set_security_answer(form.cleaned_data["security_answer"])
                operator.save()
                license_services.activate_license(duration_days=365)

            auth_login(request, user)
            config.last_logged_in_username = user.get_username()
            config.save(update_fields=["last_logged_in_username"])
            return redirect("core:dashboard")
    else:
        form = FirstOperatorSetupForm()

    return render(request, "accounts/first_setup.html", {"form": form})


def _get_the_operator():
    """This is a single-operator application (see FirstOperatorSetupForm's
    docstring) -- there is at most one Operator row, so password recovery
    never needs to ask "which account", only "what's the answer"."""
    return Operator.objects.select_related("user").first()


def forgot_password(request):
    """
    Step 1 of password recovery: show the operator's own stored security
    question and let them answer it. A correct answer marks the session
    as verified and redirects to reset_password; a wrong answer re-shows
    the same question with an error, never revealing anything about the
    stored answer itself.
    """
    operator = _get_the_operator()
    if operator is None:
        # No account exists yet -- nothing to recover.
        return redirect("accounts:login")

    if request.method == "POST":
        form = SecurityAnswerForm(request.POST)
        if form.is_valid():
            if operator.check_security_answer(form.cleaned_data["answer"]):
                request.session[RECOVERY_VERIFIED_SESSION_KEY] = True
                return redirect("accounts:reset_password")
            form.add_error("answer", "پاسخ صحیح نیست.")
    else:
        form = SecurityAnswerForm()

    return render(
        request, "accounts/forgot_password.html",
        {"form": form, "security_question": operator.security_question},
    )


def reset_password(request):
    """
    Step 2 of password recovery: set a new password. Only reachable after
    forgot_password has verified the security answer this session --
    guards against reaching this page directly by URL. The verified flag
    is consumed (removed) as soon as the new password is saved, so it
    can't be reused for a second reset without answering the question
    again.
    """
    operator = _get_the_operator()
    if operator is None or not request.session.get(RECOVERY_VERIFIED_SESSION_KEY):
        return redirect("accounts:forgot_password")

    if request.method == "POST":
        form = OperatorSetPasswordForm(operator.user, request.POST)
        if form.is_valid():
            form.save()
            del request.session[RECOVERY_VERIFIED_SESSION_KEY]
            return redirect("accounts:login")
    else:
        form = OperatorSetPasswordForm(operator.user)

    return render(request, "accounts/reset_password.html", {"form": form})
