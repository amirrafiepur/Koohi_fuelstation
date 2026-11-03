from django.contrib import admin

from .models import Station, Product, Tank, Nozzle

admin.site.register(Station)
admin.site.register(Product)
admin.site.register(Tank)
admin.site.register(Nozzle)
