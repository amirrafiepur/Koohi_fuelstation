from django.urls import path

from . import views

app_name = "purchases"

urlpatterns = [
    path("", views.invoice_list, name="invoice_list"),
    path("choose-date/", views.choose_working_date, name="choose_date"),
    path("<str:date>/tank/<int:tank_id>/new/", views.purchase_entry, name="purchase_entry"),
    path("<str:date>/invoice/<int:pk>/edit/", views.purchase_edit, name="purchase_edit"),
    path("<str:date>/invoice/<int:pk>/delete/", views.purchase_delete, name="purchase_delete"),
]
