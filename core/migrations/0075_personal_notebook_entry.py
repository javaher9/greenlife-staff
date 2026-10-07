from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0074_jobduty_target_user'),
    ]

    operations = [
        migrations.CreateModel(
            name='PersonalNotebookEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('body', models.TextField(max_length=2000)),
                ('reminder_date', models.DateField(blank=True, db_index=True, null=True)),
                ('is_pinned', models.BooleanField(db_index=True, default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='personal_notebook_entries', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-is_pinned', '-updated_at', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='personalnotebookentry',
            index=models.Index(fields=['user', '-updated_at'], name='pnote_user_updated_idx'),
        ),
    ]
