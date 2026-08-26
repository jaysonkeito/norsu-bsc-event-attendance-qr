# Generated migration for College model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('qrapp', '0005_rename_course_to_program'),
    ]

    operations = [
        # Create College model
        migrations.CreateModel(
            name='College',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(help_text='Short code (e.g., CCJE, CTED)', max_length=20, unique=True)),
                ('name', models.CharField(help_text='Full college name', max_length=200)),
                ('is_active', models.BooleanField(default=True, help_text='Active colleges appear in dropdowns')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'College',
                'verbose_name_plural': 'Colleges',
                'ordering': ['code'],
            },
        ),
        # Change Student college field to allow longer values
        migrations.AlterField(
            model_name='student',
            name='college',
            field=models.CharField(help_text='College code or name', max_length=100),
        ),
    ]
