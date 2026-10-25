from django.db import migrations, models


def preserve_existing_access(apps, schema_editor):
    EmployeeProfile=apps.get_model('core','EmployeeProfile')
    PaymentRequest=apps.get_model('payments','PaymentRequest')
    EmployeeProfile.objects.filter(role='consultant',is_active=True).update(can_request_payments=True,can_manage_petty_cash=True)
    assigned_ids=PaymentRequest.objects.filter(state='approved',assigned_to_id__isnull=False).values_list('assigned_to_id',flat=True).distinct()
    EmployeeProfile.objects.filter(user_id__in=assigned_ids).update(can_execute_payments=True)
    # Existing consultants are permitted to complete payments, retaining their live workflow.
    EmployeeProfile.objects.filter(role='consultant',is_active=True).update(can_execute_payments=True)
    # Retain live payment responsibility for the five previously authorized operators.
    for profile in EmployeeProfile.objects.filter(is_active=True,user__is_active=True).select_related('user').exclude(role__in=('referrer','referral_supervisor','scan_station')):
        name=' '.join((profile.user.first_name or '',profile.user.last_name or '',profile.user.username or '')).replace('ي','ی').replace('ك','ک').lower()
        known=(('صادقی' in name or 'sadeghi' in name)
               or ('نادری' in name or 'naderi' in name)
               or ('مرادی' in name or 'moradi' in name)
               or (('معماری' in name or 'memari' in name) and ('مرجان' in name or 'marjan' in name))
               or (('حسینی' in name or 'hosseini' in name) and ('زینب' in name or 'zeinab' in name or 'zeynab' in name or 'حسابدار' in (profile.job_title or ''))))
        if known and not profile.can_execute_payments:
            profile.can_execute_payments=True
            profile.save(update_fields=['can_execute_payments'])



class Migration(migrations.Migration):
    dependencies=[('core','0099_payment_request_permission'),('payments','0002_clarification')]
    operations=[
        migrations.AddField(model_name='employeeprofile',name='can_execute_payments',field=models.BooleanField(default=False,help_text='اجازه اجرای دستور پرداخت ارجاع‌شده')),
        migrations.AddField(model_name='employeeprofile',name='can_manage_petty_cash',field=models.BooleanField(default=False,help_text='اجازه درخواست تنخواه و ثبت هزینه آن')),
        migrations.AddField(model_name='employeeprofile',name='can_claim_personal_expense',field=models.BooleanField(default=False,help_text='اجازه ثبت هزینه پرداخت‌شده از حساب شخصی برای بازپرداخت')),
        migrations.RunPython(preserve_existing_access,migrations.RunPython.noop),
    ]
