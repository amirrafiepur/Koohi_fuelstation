from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='operator',
            name='security_question',
            field=models.CharField(default='', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='operator',
            name='security_answer_hash',
            field=models.CharField(default='', max_length=255),
            preserve_default=False,
        ),
    ]
