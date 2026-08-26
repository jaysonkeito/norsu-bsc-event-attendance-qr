# Data migration to populate Program table with default programs per college

from django.db import migrations


def populate_programs(apps, schema_editor):
    """Populate Program table with default programs for each college"""
    College = apps.get_model('qrapp', 'College')
    Program = apps.get_model('qrapp', 'Program')
    
    # Define programs for each college
    programs_data = {
        'CAS': [
            {'code': 'BSCS', 'name': 'Bachelor of Science in Computer Science'},
            {'code': 'BSIT', 'name': 'Bachelor of Science in Information Technology'},
        ],
        'CTED': [
            {'code': 'BEED', 'name': 'Bachelor of Elementary Education'},
            {'code': 'BSED-Math', 'name': 'Bachelor of Secondary Education (Major in Math)'},
            {'code': 'BSED-Science', 'name': 'Bachelor of Secondary Education (Major in Science)'},
        ],
        'CIT': [
            {'code': 'Com. Tech', 'name': 'Computer Technology'},
            {'code': 'Automotive', 'name': 'Automotive Technology'},
            {'code': 'Electrical', 'name': 'Electrical Technology'},
        ],
        'CBA': [
            {'code': 'BSOA', 'name': 'Bachelor of Science in Office Administration'},
            {'code': 'BSHM', 'name': 'Bachelor of Science in Hospitality Management'},
            {'code': 'BSBA', 'name': 'Bachelor of Science in Business Administration'},
        ],
        'CAF': [
            {'code': 'Agronomy', 'name': 'Agronomy'},
            {'code': 'Forestry', 'name': 'Forestry'},
            {'code': 'Animal Science', 'name': 'Animal Science'},
        ],
        'CCJE': [
            {'code': 'BSCRIM', 'name': 'Bachelor of Science in Criminology'},
        ],
    }
    
    # Create programs for each college
    for college_code, programs in programs_data.items():
        try:
            college = College.objects.get(code=college_code)
            for program_data in programs:
                Program.objects.get_or_create(
                    college=college,
                    code=program_data['code'],
                    defaults={
                        'name': program_data['name'],
                        'is_active': True
                    }
                )
        except College.DoesNotExist:
            print(f"Warning: College {college_code} not found, skipping programs")


def reverse_populate_programs(apps, schema_editor):
    """Remove programs if migration is reversed"""
    Program = apps.get_model('qrapp', 'Program')
    Program.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('qrapp', '0008_add_program_model'),
    ]

    operations = [
        migrations.RunPython(populate_programs, reverse_populate_programs),
    ]
