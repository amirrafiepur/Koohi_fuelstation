from django.urls import path

from . import views

app_name = "license"

urlpatterns = [
    path("renew/", views.renew, name="renew"),
]
