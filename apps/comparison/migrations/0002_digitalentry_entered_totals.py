from decimal import Decimal

from django.db import migrations, models


def keep_existing_figures(apps, schema_editor):
    """
    The two totals and the second آزمایش used to be calculated on the fly from the
    row's other entered values. They are now stored (typed in by the user), so every
    existing row is given exactly the figures it displayed before -- historical
    months keep showing the same numbers. Nothing is deleted or overwritten.
    """
    DigitalEntry = apps.get_model("comparison", "DigitalEntry")
    for entry in DigitalEntry.objects.all():
        entry.received_total = (
            entry.beginning_inventory + entry.received_quantity + entry.test_return + entry.overage
        )
        entry.dispatched_test_return = entry.test_return
        entry.dispatched_total = (
            entry.sales_quantity + entry.test_return + entry.shortage + entry.ending_inventory
        )
        entry.save(update_fields=["received_total", "dispatched_test_return", "dispatched_total"])


class Migration(migrations.Migration):

    dependencies = [
        ("comparison", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="digitalentry",
            name="received_total",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14, verbose_name="جمع کل"),
        ),
        migrations.AddField(
            model_name="digitalentry",
            name="dispatched_test_return",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), help_text="The آزمایش column of the خارج شده side.", max_digits=14, verbose_name="آزمایش"),
        ),
        migrations.AddField(
            model_name="digitalentry",
            name="dispatched_total",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14, verbose_name="جمع کل خارج شده"),
        ),
        migrations.RunPython(keep_existing_figures, migrations.RunPython.noop),
    ]
