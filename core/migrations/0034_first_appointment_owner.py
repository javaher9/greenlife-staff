from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_first_owners(apps, schema_editor):
    ReferralLead=apps.get_model('core','ReferralLead')
    VisitAppointment=apps.get_model('core','VisitAppointment')
    FinancialTransaction=apps.get_model('core','FinancialTransaction')

    earliest={}
    appointments=VisitAppointment.objects.filter(
        lead_id__isnull=False,source='call_center',created_by_id__isnull=False,
    ).order_by('created_at','id').values_list('lead_id','created_by_id')
    for lead_id,user_id in appointments.iterator():
        earliest.setdefault(lead_id,user_id)
    for lead_id,user_id in earliest.items():
        ReferralLead.objects.filter(pk=lead_id,first_appointment_by_id__isnull=True).update(
            first_appointment_by_id=user_id,
        )

    transactions=FinancialTransaction.objects.filter(
        appointment_id__isnull=False,call_center_owner_id__isnull=True,
    ).select_related('appointment__lead').iterator()
    for item in transactions:
        appointment=item.appointment
        owner_id=None
        if appointment.lead_id:
            owner_id=earliest.get(appointment.lead_id)
        owner_id=owner_id or appointment.created_by_id
        if owner_id:
            FinancialTransaction.objects.filter(pk=item.pk).update(call_center_owner_id=owner_id)


class Migration(migrations.Migration):
    dependencies=[('core','0033_consultant_sales_attribution')]

    operations=[
        migrations.AddField(
            model_name='referrallead',name='first_appointment_by',
            field=models.ForeignKey(blank=True,help_text='مالک دائمی مراجعه؛ کاربری که اولین نوبت کال‌سنتر را ثبت کرده است.',null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='first_owned_referral_leads',to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='financialtransaction',name='call_center_owner',
            field=models.ForeignKey(blank=True,help_text='گل کال‌سنتر که اولین نوبت این مراجعه را ثبت کرده است.',null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='attributed_financial_transactions',to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(backfill_first_owners,migrations.RunPython.noop),
    ]
