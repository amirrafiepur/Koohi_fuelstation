"""
Purchase forms.

Per the mandatory Phase 5 rules: no uniqueness validation is applied to
tanker_number or document_number (rule 2), and tanker_capacity carries no
restriction of any kind (rule 3) -- this form must never add validation
beyond what the model already omits.

Per the Purchases section rework, the operator-facing form only exposes
program_number ("شماره ی بارنامه"), tanker_number ("شماره ی نفتکش"),
quantity ("مقدار"), and purchase_rate ("نرخ"). document_number,
tanker_capacity, and unloading_time remain on the PurchaseInvoice model
(existing historical data and the rules above still apply to them) but
are intentionally no longer collected through this form or shown in the
purchases UI.
"""

from django import forms

from .models import PurchaseInvoice


class PurchaseInvoiceForm(forms.ModelForm):
    class Meta:
        model = PurchaseInvoice
        fields = ["program_number", "tanker_number", "quantity", "purchase_rate"]
        widgets = {
            "program_number": forms.TextInput(attrs={"class": "form-input", "autofocus": True}),
            "tanker_number": forms.TextInput(attrs={"class": "form-input"}),
            "quantity": forms.NumberInput(attrs={"class": "form-input numeric"}),
            "purchase_rate": forms.NumberInput(attrs={"class": "form-input numeric", "step": "0.01"}),
        }
        labels = {
            "program_number": "شماره ی بارنامه",
            "tanker_number": "شماره ی نفتکش",
            "quantity": "مقدار",
            "purchase_rate": "نرخ",
        }
