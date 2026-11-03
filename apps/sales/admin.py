from django.contrib import admin

from .models import SalesInvoice, NozzleSale

admin.site.register(SalesInvoice)
admin.site.register(NozzleSale)
