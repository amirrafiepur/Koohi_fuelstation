from django.urls import path

from . import views

app_name = "comparison"

urlpatterns = [
    path("", views.comparison, name="comparison"),
    path("entry/<int:entry_id>/edit/", views.digital_entry_edit, name="digital_entry_edit"),
]
