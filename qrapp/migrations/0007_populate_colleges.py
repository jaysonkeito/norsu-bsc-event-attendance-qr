# Data migration to populate College table with default values

from django.db import migrations


def populate_colleges(apps, schema_editor):
    """Populate College table with default college data"""
    College = apps.get_model('qrapp', 'College')
    
    default_colleges = [
        {'code': 'CCJE', 'name': 'College of Criminal Justice Education', 'is_active': True},
        {'code': 'CTED', 'name': 'College of Teacher Education', 'is_active': True},
        {'code': 'CIT', 'name': 'College of Industrial Technology', 'is_active': True},
        {'code': 'CBA', 'name': 'College of Business Administration', 'is_active': True},
        {'code': 'CAS', 'name': 'College of Arts and Sciences', 'is_active': True},
        {'code': 'CAF', 'name': 'College of Agriculture and Forestry', 'is_active': True},
    ]
    
    for college_data in default_colleges:
        College.objects.get_or_create(
            code=college_data['code'],
            defaults={
                'name': college_data['name'],
                'is_active': college_data['is_active']
            }
        )


def reverse_populate_colleges(apps, schema_editor):
    """Remove colleges if migration is reversed"""
    College = apps.get_model('qrapp', 'College')
    College.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('qrapp', '0006_add_college_model'),
    ]

    operations = [
        migrations.RunPython(populate_colleges, reverse_populate_colleges),
    ]
