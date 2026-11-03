from django.urls import path

from . import views

app_name = "statement"

urlpatterns = [
    path("", views.statement, name="statement"),
    path("entry/<int:entry_id>/digital-sales/", views.digital_sales_entry, name="digital_sales_entry"),
    path("entry/<int:entry_id>/tanker-capacity/", views.tanker_capacity_entry, name="tanker_capacity_entry"),
]
