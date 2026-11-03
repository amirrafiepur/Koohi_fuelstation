from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("nozzle-ledger/", views.nozzle_performance_ledger, name="nozzle_ledger"),
    path("all-nozzles/", views.all_nozzles_performance, name="all_nozzles_summary"),
    path("nozzle-monthly/", views.nozzle_performance_monthly, name="nozzle_monthly"),
    path("petroleum-ledger/", views.petroleum_inventory_operations_ledger, name="petroleum_ledger"),
    path("petroleum-monthly/", views.petroleum_inventory_monthly, name="petroleum_monthly"),
]
