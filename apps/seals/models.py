"""
NozzleSeal is event-based, NOT a daily record: a row is created only when a
seal is installed or replaced, not once per working day.
"""

from django.db import models

from apps.stations.models import Nozzle


class NozzleSeal(models.Model):
    FLAG_DOOR_1 = "flag_door_1"
    FLAG_DOOR_2 = "flag_door_2"
    PUMP_DOOR_1 = "pump_door_1"
    PUMP_DOOR_2 = "pump_door_2"
    SECTION_CHOICES = [
        (FLAG_DOOR_1, "درب پرچمی 1"),
        (FLAG_DOOR_2, "درب پرچمی 2"),
        (PUMP_DOOR_1, "درب تلمبه 1"),
        (PUMP_DOOR_2, "درب تلمبه 2"),
    ]

    nozzle = models.ForeignKey(
        Nozzle, on_delete=models.PROTECT, related_name="seals"
    )
    section = models.CharField(max_length=20, choices=SECTION_CHOICES)
    date = models.DateField()
    seal_number = models.CharField(max_length=100)

    class Meta:
        verbose_name = "Nozzle Seal"
        verbose_name_plural = "Nozzle Seals"
        ordering = ["-date"]

    def __str__(self):
        return f"Nozzle {self.nozzle.number} — {self.get_section_display()} — {self.date}"
