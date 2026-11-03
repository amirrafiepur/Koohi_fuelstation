from django import forms


class LicenseRenewalForm(forms.Form):
    password = forms.CharField(
        label="رمز تمدید لایسنس",
        widget=forms.PasswordInput(attrs={"class": "form-input", "autofocus": True}),
    )
