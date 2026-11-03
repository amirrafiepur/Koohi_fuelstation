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


class Command(BaseCommand):
    help = "Seed the fixed station/product/tank/nozzle configuration."

    @transaction.atomic
    def handle(self, *args, **options):
        station, created = Station.objects.get_or_create(
            name="140 Jahan Pour",
            defaults={"province": "Razavi Khorasan", "city": "Mashhad"},
        )
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
