"""
Seeds the fixed station configuration: the station itself, the two
products (Regular petrol and CNG), the two tanks, and all 18 nozzles
with their fixed tank assignment: regular petrol nozzles 1-14 and CNG
nozzles CNG 1-4 (numbered independently of the regular nozzles).

This configuration is NOT editable through a GUI in Phase 1 -- per the
architecture doc, future nozzle changes are made directly via this
management command / the Django admin, not through end-user UI.

Usage: python manage.py seed_station
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.stations.models import Station, Product, Tank, Nozzle

REGULAR_NOZZLES = list(range(1, 15))   # regular petrol nozzles 1-14
CNG_NOZZLES = list(range(1, 5))        # CNG 1 - CNG 4 (own numbering)
EXPECTED_NOZZLE_COUNT = len(REGULAR_NOZZLES) + len(CNG_NOZZLES)
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
        cng, _ = Product.objects.get_or_create(name="CNG")

        regular_tank, _ = Tank.objects.get_or_create(
            station=station, product=regular, defaults={"capacity": 0}
        )
        cng_tank, _ = Tank.objects.get_or_create(
            station=station, product=cng, defaults={"capacity": 0}
        )

        created_count = 0
        # Nozzle numbers are unique per tank (product), so CNG 1-4 never
        # collide with -- or get mistaken for -- regular nozzles.
        for tank, numbers in ((regular_tank, REGULAR_NOZZLES), (cng_tank, CNG_NOZZLES)):
            for number in numbers:
                _, was_created = Nozzle.objects.get_or_create(
                    tank=tank, number=number
                )
                created_count += int(was_created)

        total_nozzles = Nozzle.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Nozzles: {created_count} newly created, {total_nozzles} total "
                f"(expected {EXPECTED_NOZZLE_COUNT})."
            )
        )
        if total_nozzles != EXPECTED_NOZZLE_COUNT:
            self.stdout.write(
                self.style.WARNING(
                    f"Total nozzle count is not {EXPECTED_NOZZLE_COUNT} -- check for a "
                    "prior partial seed or a database created for the previous "
                    "station layout."
                )
            )
