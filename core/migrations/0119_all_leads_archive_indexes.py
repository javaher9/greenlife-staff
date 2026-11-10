from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0118_fill_existing_doctor_recommendations_from_excel')]
    operations = [
        migrations.AddIndex(model_name='referrallead', index=models.Index(fields=['created_at', 'id'], name='reflead_archive_cursor_idx')),
        migrations.AddIndex(model_name='visitappointment', index=models.Index(fields=['lead', '-created_at', '-id'], name='visitappt_lead_latest_idx')),
    ]
