# Generated migration for Program model

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('qrapp', '0007_populate_colleges'),
    ]

    operations = [
        migrations.CreateModel(
            name='Program',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(help_text='Program code (e.g., BSCS, BSIT)', max_length=50)),
                ('name', models.CharField(help_text='Full program name', max_length=200)),
                ('is_active', models.BooleanField(default=True, help_text='Active programs appear in dropdowns')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('college', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='programs', to='qrapp.college')),
            ],
            options={
                'verbose_name': 'Program',
                'verbose_name_plural': 'Programs',
                'ordering': ['college__code', 'code'],
                'unique_together': {('college', 'code')},
            },
        ),
    ]
