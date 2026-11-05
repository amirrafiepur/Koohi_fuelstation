"""
Seeds the fixed station configuration: the station itself, the two
products, the two tanks, and all 26 nozzles with their fixed tank
assignment.

This configuration is NOT editable through a GUI in Phase 1 -- per the
architecture doc, future nozzle changes are made directly via this
management command / the Django admin, not through end-user UI.

Usage: python manage.py seed_station
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.stations.models import Station, Product, Tank, Nozzle

REGULAR_NOZZLES = list(range(1, 19)) + [25, 26]
SUPER_NOZZLES = list(range(19, 25))
STATION_NAME = "Koohi 118"
# Name stored by databases created for the previous station.
LEGACY_STATION_NAME = "140 Jahan Pour"


class Command(BaseCommand):
    help = "Seed the fixed station/product/tank/nozzle configuration."

    @transaction.atomic
    def handle(self, *args, **options):
        station = Station.objects.filter(name=STATION_NAME).first()
        created = False
        if station is None:
            # A database created before the identity change holds the
            # previous station's single Station row. Re-label THAT row
            # instead of creating a second Station beside it: tanks and
            # everything hanging off them must stay attached to one
            # station. Only the name changes; province/city and every
            # accounting record are untouched.
            station = Station.objects.filter(name=LEGACY_STATION_NAME).first()
            if station is not None:
                station.name = STATION_NAME
                station.save(update_fields=["name"])
            else:
                station = Station.objects.create(
                    name=STATION_NAME, province="Razavi Khorasan", city="Mashhad"
                )
                created = True
        self.stdout.write(
            self.style.SUCCESS(f"Station: {station} ({'created' if created else 'already existed'})")
        )

        regular, _ = Product.objects.get_or_create(name="Regular")
        super_, _ = Product.objects.get_or_create(name="Super")

        regular_tank, _ = Tank.objects.get_or_create(
            station=station, product=regular, defaults={"capacity": 0}
        )
        super_tank, _ = Tank.objects.get_or_create(
            station=station, product=super_, defaults={"capacity": 0}
        )

        created_count = 0
        for number in REGULAR_NOZZLES:
            _, was_created = Nozzle.objects.get_or_create(
                number=number, defaults={"tank": regular_tank}
            )
            created_count += int(was_created)

        for number in SUPER_NOZZLES:
            _, was_created = Nozzle.objects.get_or_create(
                number=number, defaults={"tank": super_tank}
            )
            created_count += int(was_created)

        total_nozzles = Nozzle.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Nozzles: {created_count} newly created, {total_nozzles} total "
                f"(expected 26)."
            )
        )
        if total_nozzles != 26:
            self.stdout.write(
                self.style.WARNING(
                    "Total nozzle count is not 26 -- check for a prior partial seed."
                )
            )
