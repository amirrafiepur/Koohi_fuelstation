"""Authentication and first-run account setup forms."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm, UserCreationForm
from django.contrib.auth import get_user_model


User = get_user_model()


class OperatorLoginForm(AuthenticationForm):
    username = forms.CharField(
        label="نام کاربری",
        widget=forms.TextInput(attrs={"autofocus": True, "class": "form-input"}),
    )
    password = forms.CharField(
        label="گذرواژه",
        widget=forms.PasswordInput(attrs={"class": "form-input"}),
    )


class FirstOperatorSetupForm(UserCreationForm):
    """First-run account creation; this form must never be available again.

    Also collects a security question/answer pair used solely for the
    "forgot password" recovery flow (see apps/accounts/models.py's
    Operator.set_security_answer/check_security_answer) -- the view is
    responsible for calling those, this form only captures the raw input."""

    setup_password = forms.CharField(
        label="رمز راه‌اندازی",
        widget=forms.PasswordInput(attrs={"class": "form-input", "autofocus": True}),
    )
    security_question = forms.CharField(
        label="یک سوال رمزی در صورت فراموش کردن رمز عبور خود وارد کنید:",
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    security_answer = forms.CharField(
        label="جواب سوالی که وارد کردید را وارد کنید:",
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )

    class Meta:
        model = User
        fields = ("username", "password1", "password2")
        labels = {
            "username": "نام کاربری",
        }
        widgets = {
            "username": forms.TextInput(
                attrs={"autofocus": True, "class": "form-input"}
            ),
            "password1": forms.PasswordInput(attrs={"class": "form-input"}),
            "password2": forms.PasswordInput(attrs={"class": "form-input"}),
        }


class SecurityAnswerForm(forms.Form):
    """Step 1 of password recovery: the operator must answer their own
    stored security question correctly before being allowed to set a new
    password. The view compares the answer via
    Operator.check_security_answer() -- this form only captures the raw
    input, it never sees or compares against the stored hash itself."""

    answer = forms.CharField(
        label="پاسخ",
        widget=forms.TextInput(attrs={"autofocus": True, "class": "form-input"}),
    )


class OperatorSetPasswordForm(SetPasswordForm):
    """Step 2 of password recovery: choose a new password. Reuses Django's
    own SetPasswordForm (validation, hashing, save()) -- only the labels
    are localized."""

    new_password1 = forms.CharField(
        label="گذرواژه جدید",
        widget=forms.PasswordInput(attrs={"autofocus": True, "class": "form-input"}),
        strip=False,
    )
    new_password2 = forms.CharField(
        label="تکرار گذرواژه جدید",
        widget=forms.PasswordInput(attrs={"class": "form-input"}),
        strip=False,
    )
