from django.db import migrations, models


def preserve_existing_access(apps, schema_editor):
    EmployeeProfile=apps.get_model('core','EmployeeProfile')
    PaymentRequest=apps.get_model('payments','PaymentRequest')
    EmployeeProfile.objects.filter(role='consultant',is_active=True).update(can_request_payments=True)
    assigned_ids=PaymentRequest.objects.filter(state='approved',assigned_to_id__isnull=False).values_list('assigned_to_id',flat=True).distinct()
    EmployeeProfile.objects.filter(user_id__in=assigned_ids).update(can_execute_payments=True)
    # Existing consultants are permitted to complete payments, retaining their live workflow.
    EmployeeProfile.objects.filter(role='consultant',is_active=True).update(can_execute_payments=True)


class Migration(migrations.Migration):
    dependencies=[('core','0099_payment_request_permission'),('payments','0002_clarification')]
    operations=[
        migrations.AddField(model_name='employeeprofile',name='can_execute_payments',field=models.BooleanField(default=False,help_text='اجازه اجرای دستور پرداخت ارجاع‌شده')),
        migrations.AddField(model_name='employeeprofile',name='can_manage_petty_cash',field=models.BooleanField(default=False,help_text='اجازه درخواست تنخواه و ثبت هزینه آن')),
        migrations.AddField(model_name='employeeprofile',name='can_claim_personal_expense',field=models.BooleanField(default=False,help_text='اجازه ثبت هزینه پرداخت‌شده از حساب شخصی برای بازپرداخت')),
        migrations.RunPython(preserve_existing_access,migrations.RunPython.noop),
    ]
