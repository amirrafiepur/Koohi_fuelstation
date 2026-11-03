from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path("", views.choose_working_date, name="choose_date"),
    path("invoices/", views.invoice_list, name="invoice_list"),
    path("invoices/<str:date>/", views.invoice_detail, name="invoice_detail"),
    path("invoices/<str:date>/nozzle/", views.nozzle_entry, name="nozzle_entry_next"),
    path("invoices/<str:date>/nozzle/<int:nozzle_number>/", views.nozzle_entry, name="nozzle_entry"),
]
