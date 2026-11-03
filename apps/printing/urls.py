from django.urls import path

from . import views

app_name = "printing"

urlpatterns = [
    path("nozzle-ledger/<int:nozzle_id>/", views.nozzle_ledger_print, name="nozzle_ledger_print"),
    path("all-nozzles/", views.all_nozzles_performance_print, name="all_nozzles_performance_print"),
    path("nozzle-monthly/", views.nozzle_monthly_print, name="nozzle_monthly_print"),
    path("petroleum-ledger/<int:tank_id>/", views.petroleum_ledger_print, name="petroleum_ledger_print"),
    path("petroleum-monthly/", views.petroleum_monthly_print, name="petroleum_monthly_print"),
    path("purchases-ledger/", views.purchases_ledger_print, name="purchases_ledger_print"),
    path("deposits-decade/", views.deposit_decade_print, name="deposit_decade_print"),
    path("statement/", views.statement_print, name="statement_print"),
    path("comparison/", views.comparison_print, name="comparison_print"),
    path("seals/", views.seals_print, name="seals_print"),
    path("sales-invoice/<str:date>/", views.sales_invoice_print, name="sales_invoice_print"),
]
