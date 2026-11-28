from django import forms

from .models import DigitalEntry


class DigitalEntryForm(forms.ModelForm):
    class Meta:
        model = DigitalEntry
        fields = [
            "beginning_inventory", "received_quantity", "test_return", "overage", "received_total",
            "sales_quantity", "dispatched_test_return", "shortage", "ending_inventory", "dispatched_total",
        ]
        widgets = {
            field: forms.NumberInput(attrs={"class": "form-input numeric", "step": "0.01"})
            for field in fields
        }
