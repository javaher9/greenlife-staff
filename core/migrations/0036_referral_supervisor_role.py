from django.db import migrations, models


def assign_faramarz_eybpoosh(apps, schema_editor):
    EmployeeProfile=apps.get_model('core','EmployeeProfile')
    EmployeeProfile.objects.filter(
        user__first_name__contains='فرامرز',user__last_name__contains='عیب',user__is_active=True,
    ).update(role='referral_supervisor',job_title='ناظر شبکه فروش')


def unassign_faramarz_eybpoosh(apps, schema_editor):
    EmployeeProfile=apps.get_model('core','EmployeeProfile')
    EmployeeProfile.objects.filter(
        user__first_name__contains='فرامرز',user__last_name__contains='عیب',
        role='referral_supervisor',
    ).update(role='employee')


class Migration(migrations.Migration):
    dependencies=[('core','0035_instagram_new_group')]
    operations=[
        migrations.AlterField(
            model_name='employeeprofile',name='role',
            field=models.CharField(
                default='employee',max_length=20,
                choices=[
                    ('admin','مدیر سیستم'),('internal_manager','مدیر داخلی'),('manager','مدیر شعبه'),
                    ('referral_supervisor','ناظر شبکه فروش'),('call_center','کال‌سنتر'),
                    ('consultant','مشاور'),('receptionist','منشی'),('employee','کارمند'),
                    ('referrer','معرف مشتری'),
                ],
            ),
        ),
        migrations.AlterField(
            model_name='checklisttemplate',name='role',
            field=models.CharField(
                blank=True,max_length=20,
                choices=[
                    ('admin','مدیر سیستم'),('internal_manager','مدیر داخلی'),('manager','مدیر شعبه'),
                    ('referral_supervisor','ناظر شبکه فروش'),('call_center','کال‌سنتر'),
                    ('consultant','مشاور'),('receptionist','منشی'),('employee','کارمند'),
                    ('referrer','معرف مشتری'),
                ],
            ),
        ),
        migrations.RunPython(assign_faramarz_eybpoosh,unassign_faramarz_eybpoosh),
    ]
