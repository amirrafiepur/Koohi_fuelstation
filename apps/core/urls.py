from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("set-date/", views.set_global_date, name="set_global_date"),
]
