"""
Root URL configuration. Each app owns its own urls.py; this file only
mounts them under a namespace, per the architecture doc's page tree.
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.core.urls')),
    path('accounts/', include('apps.accounts.urls')),
    path('license/', include('apps.license.urls')),
    path('sales/', include('apps.sales.urls')),
    path('purchases/', include('apps.purchases.urls')),
    path('inventory/', include('apps.inventory.urls')),
    path('reports/', include('apps.reports.urls')),
    path('seals/', include('apps.seals.urls')),
    path('deposits/', include('apps.deposits.urls')),
    path('statement/', include('apps.statement.urls')),
    path('comparison/', include('apps.comparison.urls')),
    path('print/', include('apps.printing.urls')),
]
