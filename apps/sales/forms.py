"""
Sales forms.

NozzleSaleForm handles the "New Meter < Previous Meter" case as a
non-blocking warning (per architecture doc §18): the form validates
normally and saves regardless, but the view surfaces a warning message and
requires a second, explicit confirmation POST before actually saving. This
keeps the warning out of Django's ValidationError machinery entirely, so
it can never accidentally become a hard rejection.
"""

from django import forms

from apps.core.display import trim_trailing_zeros
from apps.core.jalali import JalaliDateField

from .models import NozzleSale


class WorkingDateForm(forms.Form):
    """Used to choose/confirm which working date the operator is entering
    data for. The view is responsible for checking can_enter_date() --
    this form only captures the input."""

    date = JalaliDateField(label="تاریخ کاری")


class NozzleSaleForm(forms.ModelForm):
    class Meta:
        model = NozzleSale
        fields = ["previous_meter", "new_meter", "test", "sales_rate"]
        widgets = {
            "previous_meter": forms.NumberInput(attrs={"class": "form-input numeric", "step": "0.01"}),
            "new_meter": forms.NumberInput(attrs={"class": "form-input numeric", "step": "0.01", "autofocus": True}),
            "test": forms.NumberInput(attrs={"class": "form-input numeric", "step": "0.01"}),
            "sales_rate": forms.NumberInput(attrs={"class": "form-input numeric", "step": "0.01"}),
        }
        labels = {
            "previous_meter": "کنتور قبلی",
            "new_meter": "کنتور جدید",
            "test": "تست",
            "sales_rate": "نرخ فروش",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Display only: the "کنتور قبلی" value shown in the form -- whether
        # pre-filled from the nozzle's last new meter or loaded from an
        # existing record -- drops a pointless ".00" tail (1334572.00 ->
        # 1334572), like every table in the app. A genuine fractional value
        # is kept (100.50 -> 100.5). The stored Decimal is never touched,
        # and the submitted string parses to exactly the same Decimal, so
        # saving and every calculation are unaffected.
        shown = self.initial.get("previous_meter")
        if shown is not None:
            self.initial["previous_meter"] = trim_trailing_zeros(shown)

    def has_negative_meter_movement(self) -> bool:
        """True when New Meter < Previous Meter -- the view uses this to
        decide whether to show the non-blocking warning and require
        confirmation before saving."""
        if not self.is_valid():
            return False
        return self.cleaned_data["new_meter"] < self.cleaned_data["previous_meter"]
