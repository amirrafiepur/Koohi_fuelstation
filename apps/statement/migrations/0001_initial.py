from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('stations', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='StatementEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year', models.PositiveIntegerField(help_text='Jalali year, e.g. 1405.')),
                ('month', models.PositiveSmallIntegerField(help_text='Jalali month, 1-12.')),
                ('digital_sales', models.DecimalField(blank=True, decimal_places=2, help_text='فروش دیجیتال -- entered manually via ورود فروش دیجیتال.', max_digits=14, null=True)),
                ('tanker_capacity', models.PositiveIntegerField(default=32000, help_text='ظرفیت نفتکش (liters). Manually editable; independent of PurchaseInvoice.tanker_capacity and of تعداد نفتکش.')),
                ('tank', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='statement_entries', to='stations.tank')),
            ],
            options={
                'verbose_name': 'Statement Entry',
                'verbose_name_plural': 'Statement Entries',
                'unique_together': {('tank', 'year', 'month')},
            },
        ),
    ]
