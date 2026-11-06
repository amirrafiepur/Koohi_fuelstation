"""
Seal forms. NozzleSeal is event-based, not a daily record -- this form
carries no chronology/working-day dependency, unlike sales/purchases/
inventory.
"""

from django import forms

from apps.core.jalali import JalaliDateField, JalaliDateWidget
from apps.stations.models import Nozzle

from .models import NozzleSeal


class NozzleChoiceField(forms.ModelChoiceField):
    """
    Displays each option as "نازل N" / "نازل CNG N" instead of Django's
    default str(nozzle) rendering (Nozzle.__str__ returns the English "Nozzle N",
    an internal/admin-facing identifier -- left unchanged; only this
    form's displayed option label is Persian).
    """

    def label_from_instance(self, obj):
        return obj.label


class NozzleSealForm(forms.ModelForm):
    # Declared explicitly, same reasoning as DepositForm: NozzleSeal.date
    # is a plain models.DateField, and ModelForm would otherwise generate
    # a Gregorian-only forms.DateField for it.
    date = JalaliDateField(label="تاریخ", widget=JalaliDateWidget())
    # Declared explicitly so the dropdown options read "نازل 1" .. "نازل 14"
    # then "نازل CNG 1" .. "نازل CNG 4" instead of ModelForm's default
    # English "Nozzle ..." labels.
    nozzle = NozzleChoiceField(
        queryset=Nozzle.objects.select_related("tank__product"),
        label="نازل",
        widget=forms.Select(attrs={"class": "form-input"}),
    )

    class Meta:
        model = NozzleSeal
        fields = ["nozzle", "section", "date", "seal_number"]
        widgets = {
            "section": forms.Select(attrs={"class": "form-input"}),
            "seal_number": forms.TextInput(attrs={"class": "form-input", "autofocus": True}),
        }
        labels = {
            "section": "بخش",
            "seal_number": "شماره پلمپ",
        }
