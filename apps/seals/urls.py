from django.urls import path

from . import views

app_name = "seals"

urlpatterns = [
    path("", views.seal_list, name="seal_list"),
    path("new/", views.seal_create, name="seal_create"),
    path("<int:pk>/edit/", views.seal_edit, name="seal_edit"),
    path("<int:pk>/delete/", views.seal_delete, name="seal_delete"),
]
