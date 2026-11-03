from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.choose_working_date, name="choose_date"),
    path("<str:date>/", views.day_detail, name="day_detail"),
    path("<str:date>/tank/<int:tank_id>/opening/", views.opening_inventory_entry, name="opening_inventory_entry"),
    path("<str:date>/tank/<int:tank_id>/actual/", views.actual_inventory_entry, name="actual_inventory_entry"),
]
