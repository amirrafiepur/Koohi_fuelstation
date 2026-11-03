from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('stations', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='DigitalEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year', models.PositiveIntegerField(help_text='Jalali year, e.g. 1405.')),
                ('month', models.PositiveSmallIntegerField(help_text='Jalali month, 1-12.')),
                ('beginning_inventory', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, verbose_name='موجودی اول ماه')),
                ('received_quantity', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, verbose_name='مقدار رسیده')),
                ('test_return', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, verbose_name='آزمایش')),
                ('overage', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, verbose_name='سرک')),
                ('sales_quantity', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, verbose_name='مقدار فروش')),
                ('shortage', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, verbose_name='کسری')),
                ('ending_inventory', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, verbose_name='موجودی آخر ماه')),
                ('tank', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='digital_comparison_entries', to='stations.tank')),
            ],
            options={
                'verbose_name': 'Digital Sales Entry',
                'verbose_name_plural': 'Digital Sales Entries',
                'unique_together': {('tank', 'year', 'month')},
            },
        ),
    ]
