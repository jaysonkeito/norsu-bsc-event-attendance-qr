# Generated manually for Batch 2: Student FKs + Attendance metadata

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def link_students_to_college_program(apps, schema_editor):
    Student = apps.get_model("qrapp", "Student")
    College = apps.get_model("qrapp", "College")
    Program = apps.get_model("qrapp", "Program")

    for student in Student.objects.all().iterator():
        college_raw = (student.college or "").strip() or "UNK"
        program_raw = (student.program or "").strip() or "NA"

        college_code = college_raw[:20]
        college = College.objects.filter(code__iexact=college_code).first()
        if not college:
            college = College.objects.filter(name__iexact=college_raw).first()
        if not college:
            college = College.objects.create(
                code=college_code,
                name=college_raw,
                is_active=True,
            )

        program_code = program_raw[:50]
        program = Program.objects.filter(college=college, code__iexact=program_code).first()
        if not program:
            program = Program.objects.filter(college=college, name__iexact=program_raw).first()
        if not program:
            program = Program.objects.create(
                college=college,
                code=program_code,
                name=program_raw,
                is_active=True,
            )

        student.college_fk_id = college.id
        student.program_fk_id = program.id
        student.save(update_fields=["college_fk", "program_fk"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("qrapp", "0009_populate_programs"),
    ]

    operations = [
        migrations.AddField(
            model_name="student",
            name="college_fk",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="students",
                to="qrapp.college",
            ),
        ),
        migrations.AddField(
            model_name="student",
            name="program_fk",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="students",
                to="qrapp.program",
            ),
        ),
        migrations.AddField(
            model_name="attendance",
            name="event_label",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional event/session label (e.g. Morning Assembly)",
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name="attendance",
            name="source",
            field=models.CharField(
                choices=[
                    ("camera", "Camera"),
                    ("device", "Scanner Device"),
                    ("manual", "Manual Entry"),
                ],
                default="camera",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="attendance",
            name="scanned_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="scans_recorded",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="attendance",
            name="student",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="attendance_records",
                to="qrapp.student",
            ),
        ),
        migrations.RunPython(link_students_to_college_program, noop_reverse),
        migrations.RemoveField(
            model_name="student",
            name="college",
        ),
        migrations.RemoveField(
            model_name="student",
            name="program",
        ),
        migrations.RenameField(
            model_name="student",
            old_name="college_fk",
            new_name="college",
        ),
        migrations.RenameField(
            model_name="student",
            old_name="program_fk",
            new_name="program",
        ),
        migrations.AlterModelOptions(
            name="attendance",
            options={"ordering": ["-timestamp"]},
        ),
        migrations.AlterModelOptions(
            name="student",
            options={"ordering": ["name", "student_id"]},
        ),
    ]
