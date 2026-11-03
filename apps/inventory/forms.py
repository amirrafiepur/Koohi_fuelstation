"""
Inventory forms.

OpeningInventoryForm is only ever shown for day 1 of the first accounting
month (see architecture doc "Opening Inventory Rule"): default 0, or a
real value from the operator's paper ledger if they have one. It must
never force a non-zero value.

ActualInventoryForm captures only the one manually-entered field per
tank/day -- everything else is derived (see inventory/services.py).
"""

from django import forms

from .models import TankInventory, OpeningInventory


class OpeningInventoryForm(forms.ModelForm):
    class Meta:
        model = OpeningInventory
        fields = ["opening_quantity"]
        widgets = {
            "opening_quantity": forms.NumberInput(attrs={"class": "form-input numeric", "step": "0.01"}),
        }
        labels = {
            "opening_quantity": "موجودی افتتاحیه",
        }


class ActualInventoryForm(forms.ModelForm):
    class Meta:
        model = TankInventory
        fields = ["actual_inventory"]
        widgets = {
            "actual_inventory": forms.NumberInput(attrs={"class": "form-input numeric", "step": "0.01", "autofocus": True}),
        }
        labels = {
            "actual_inventory": "موجودی واقعی",
        }
