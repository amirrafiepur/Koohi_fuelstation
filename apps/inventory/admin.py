from django.contrib import admin

from .models import TankInventory, OpeningInventory

admin.site.register(TankInventory)
admin.site.register(OpeningInventory)
