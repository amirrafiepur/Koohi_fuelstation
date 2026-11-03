"""
Deposit forms. Deposits are fully optional -- no record required when
there's no deposit activity for a period. Date defaults to the current
system date but can be adjusted for a valid historical entry (handled in
the view's initial value, not here).
"""

from django import forms

from apps.core.jalali import JalaliDateField, JalaliDateWidget

from .models import Deposit


class DepositForm(forms.ModelForm):
    # Declared explicitly (rather than left to ModelForm's auto-generation
    # from Deposit.date, a plain models.DateField) so the form reads/writes
    # Jalali text while cleaned_data/instance.date remain an ordinary
    # Gregorian date, same as every other field on this model.
    date = JalaliDateField(label="تاریخ", widget=JalaliDateWidget(attrs={"autofocus": True}))

    class Meta:
        model = Deposit
        fields = [
            "date", "year", "month", "decade",
            "difference_amount", "deposit_amount", "document_number",
        ]
        widgets = {
            "year": forms.NumberInput(attrs={"class": "form-input numeric"}),
            "month": forms.NumberInput(attrs={"class": "form-input numeric", "min": 1, "max": 12}),
            "decade": forms.Select(attrs={"class": "form-input"}),
            "difference_amount": forms.NumberInput(attrs={"class": "form-input numeric", "step": "0.01"}),
            "deposit_amount": forms.NumberInput(attrs={"class": "form-input numeric", "step": "0.01"}),
            "document_number": forms.TextInput(attrs={"class": "form-input"}),
        }
        labels = {
            "year": "سال",
            "month": "ماه",
            "decade": "دهه",
            "difference_amount": "مبلغ تفاوت",
            "deposit_amount": "مبلغ واریزی",
            "document_number": "شماره سند",
        }
