from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("qrapp", "0012_event_picture"),
    ]

    operations = [
        migrations.RenameField(
            model_name="student",
            old_name="section",
            new_name="major",
        ),
        migrations.AlterField(
            model_name="student",
            name="major",
            field=models.CharField(max_length=200),
        ),
    ]
