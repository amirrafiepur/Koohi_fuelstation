from django import forms

from .models import StatementEntry


class DigitalSalesForm(forms.ModelForm):
    """
    Minimal form for "ورود فروش دیجیتال" -- contains only فروش دیجیتال,
    per the task's explicit instruction.
    """

    class Meta:
        model = StatementEntry
        fields = ["digital_sales"]
        widgets = {
            "digital_sales": forms.NumberInput(attrs={
                "class": "form-input numeric", "step": "0.01", "autofocus": True,
            }),
        }
        labels = {"digital_sales": "فروش دیجیتال"}


class TankerCapacityForm(forms.ModelForm):
    class Meta:
        model = StatementEntry
        fields = ["tanker_capacity"]
        widgets = {
            "tanker_capacity": forms.NumberInput(attrs={"class": "form-input numeric"}),
        }
        labels = {"tanker_capacity": "ظرفیت نفتکش"}
