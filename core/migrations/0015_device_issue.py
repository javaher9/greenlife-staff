from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[('core','0014_guidelines_report_comments')]
    operations=[
        migrations.CreateModel(
            name='DeviceIssue',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('device_name',models.CharField(max_length=160)),
                ('description',models.TextField()),
                ('status',models.CharField(choices=[('new','جدید'),('reviewing','در حال بررسی'),('resolved','رفع شده')],default='new',max_length=20)),
                ('manager_note',models.TextField(blank=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('resolved_at',models.DateTimeField(blank=True,null=True)),
                ('branch',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='device_issues',to='core.branch')),
                ('reporter',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='reported_device_issues',to='auth.user')),
                ('resolved_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='resolved_device_issues',to='auth.user')),
            ],
            options={'ordering':['-created_at']},
        ),
    ]
