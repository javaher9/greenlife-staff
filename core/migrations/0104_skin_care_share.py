from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def allow_unique_haddad(apps, schema_editor):
    Profile=apps.get_model('core','EmployeeProfile')
    staff=list(Profile.objects.filter(is_active=True,user__is_active=True).select_related('user'))
    def words(p):
        u=p.user
        name=' '.join((u.first_name or '',u.last_name or '',u.username or ''))
        return set(name.replace('ي','ی').replace('ك','ک').replace('_',' ').replace('-',' ').lower().split())
    candidates=[p for p in staff if 'حداد' in words(p) or 'haddad' in words(p) or 'hadad' in words(p)]
    if len(candidates)==1:
        Profile.objects.filter(pk=candidates[0].pk).update(can_record_skin_care=True)


class Migration(migrations.Migration):
    dependencies=[('core','0103_remote_laleh_followup')]
    operations=[
        migrations.AddField(
            model_name='employeeprofile',name='can_record_skin_care',
            field=models.BooleanField(default=False,help_text='مجوز اختصاصی ثبت سهم اسکین‌کر؛ تأیید نهایی همچنان با مدیریت مالی است.'),
        ),
        migrations.AlterField(
            model_name='financialtransaction',name='sale_reason',
            field=models.CharField(max_length=30,blank=True,choices=[
                ('device_package','پکیج دستگاه'),
                ('daya_package','پکیج دایا'),
                ('lipolytic','لیپولیتیک'),
                ('skin','پوست'),
                ('skin_care','اسکین‌کر | سهم گرین‌لایف'),
                ('other','سایر'),
            ]),
        ),
        migrations.CreateModel(
            name='SkinCareSettlement',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('service_date',models.DateField(db_index=True,default=django.utils.timezone.localdate)),
                ('company_share_toman',models.DecimalField(decimal_places=0,max_digits=16)),
                ('gross_equivalent_toman',models.DecimalField(decimal_places=0,max_digits=16)),
                ('payment_method',models.CharField(max_length=30)),
                ('tracking_number',models.CharField(blank=True,max_length=100)),
                ('receipt_image',models.ImageField(blank=True,null=True,upload_to='finance/skin_care/%Y/%m/%d/')),
                ('description',models.CharField(blank=True,max_length=300)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('branch',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='skin_care_settlements',to='core.branch')),
                ('created_by',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='entered_skin_care_settlements',to='auth.user')),
                ('finance_transaction',models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,related_name='skin_care_settlement',to='core.financialtransaction')),
                ('performer',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='skin_care_settlements',to='core.employeeprofile')),
            ],
            options={'ordering':['-service_date','-id']},
        ),
        migrations.RunPython(allow_unique_haddad,migrations.RunPython.noop),
    ]
