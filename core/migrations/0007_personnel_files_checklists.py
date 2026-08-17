from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone

class Migration(migrations.Migration):
    dependencies=[('core','0006_operations_shifts_corrections_notifications')]
    operations=[
        migrations.CreateModel(
            name='ChecklistTemplate',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('name',models.CharField(max_length=140)),
                ('role',models.CharField(blank=True,choices=[('admin','مدیر سیستم'),('manager','مدیر شعبه'),('employee','کارمند')],max_length=20)),
                ('job_title',models.CharField(blank=True,help_text='اگر خالی باشد برای همه سمت‌های این نقش اعمال می‌شود.',max_length=120)),
                ('is_active',models.BooleanField(default=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('branch',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='checklist_templates',to='core.branch')),
                ('created_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='created_checklist_templates',to='auth.user')),
            ],
        ),
        migrations.CreateModel(
            name='EmployeeDocument',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('document_type',models.CharField(choices=[('contract','قرارداد'),('identity','مدرک هویتی'),('certificate','مدرک/گواهی'),('training','آموزش'),('other','سایر')],default='other',max_length=20)),
                ('title',models.CharField(max_length=160)),
                ('file',models.FileField(upload_to='personnel/%Y/%m/')),
                ('issue_date',models.DateField(blank=True,null=True)),
                ('expiry_date',models.DateField(blank=True,null=True)),
                ('note',models.TextField(blank=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('employee',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='documents',to='core.employeeprofile')),
                ('uploaded_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='uploaded_employee_documents',to='auth.user')),
            ],
            options={'ordering':['-created_at']},
        ),
        migrations.CreateModel(
            name='ChecklistItem',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('title',models.CharField(max_length=180)),
                ('description',models.TextField(blank=True)),
                ('sort_order',models.PositiveSmallIntegerField(default=0)),
                ('is_required',models.BooleanField(default=True)),
                ('template',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='items',to='core.checklisttemplate')),
            ],
            options={'ordering':['sort_order','id']},
        ),
        migrations.CreateModel(
            name='ChecklistCompletion',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('date',models.DateField(default=django.utils.timezone.localdate)),
                ('is_done',models.BooleanField(default=False)),
                ('note',models.CharField(blank=True,max_length=250)),
                ('completed_at',models.DateTimeField(blank=True,null=True)),
                ('item',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='completions',to='core.checklistitem')),
                ('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='checklist_completions',to='auth.user')),
            ],
            options={'ordering':['-date','item__sort_order']},
        ),
        migrations.AddConstraint(
            model_name='checklistcompletion',
            constraint=models.UniqueConstraint(fields=('user','item','date'),name='uniq_checklist_user_item_date'),
        ),
    ]
