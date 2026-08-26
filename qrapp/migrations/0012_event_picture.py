from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("qrapp", "0011_event_and_attendance_event_fk"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="picture",
            field=models.ImageField(
                blank=True,
                help_text="Optional image shown on the scanner for this event",
                null=True,
                upload_to="events/",
            ),
        ),
    ]
