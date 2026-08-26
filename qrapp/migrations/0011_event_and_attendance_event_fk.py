# Generated manually for Events management

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("qrapp", "0010_student_fks_and_attendance_meta"),
    ]

    operations = [
        migrations.CreateModel(
            name="Event",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True, default="")),
                ("event_date", models.DateField(default=django.utils.timezone.localdate)),
                ("start_time", models.TimeField(blank=True, null=True)),
                ("end_time", models.TimeField(blank=True, null=True)),
                ("location", models.CharField(blank=True, default="", max_length=200)),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Inactive events are hidden from scanner selection",
                    ),
                ),
                (
                    "is_current",
                    models.BooleanField(
                        default=False,
                        help_text="Marks the event currently used for live scanning",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="events_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Event",
                "verbose_name_plural": "Events",
                "ordering": ["-event_date", "-start_time", "title"],
            },
        ),
        migrations.AddField(
            model_name="attendance",
            name="event",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="attendance_records",
                to="qrapp.event",
            ),
        ),
    ]
