from django.db import migrations, models
import django.db.models.deletion
import core.models


def seed_country_engine(apps, schema_editor):
    Country = apps.get_model('core', 'Country')
    Branch = apps.get_model('core', 'Branch')
    EmployeeProfile = apps.get_model('core', 'EmployeeProfile')
    ReferralLead = apps.get_model('core', 'ReferralLead')

    iran, _ = Country.objects.update_or_create(
        code='IR',
        defaults={
            'name_english':'Iran',
            'name_local':'ایران',
            'flag_emoji':'🇮🇷',
            'primary_language':'fa',
            'secondary_language':'en',
            'currency_code':'IRR',
            'currency_symbol':'تومان',
            'timezone':'Asia/Tehran',
            'phone_prefix':'+98',
            'is_active':True,
            'sort_order':10,
        },
    )
    turkey, _ = Country.objects.update_or_create(
        code='TR',
        defaults={
            'name_english':'Türkiye',
            'name_local':'Türkiye',
            'flag_emoji':'🇹🇷',
            'primary_language':'tr',
            'secondary_language':'en',
            'currency_code':'TRY',
            'currency_symbol':'₺',
            'timezone':'Europe/Istanbul',
            'phone_prefix':'+90',
            'is_active':True,
            'sort_order':20,
        },
    )

    turkey_tokens=('istanbul','skyland','torun','türkiye','turkey','استانبول','ترکیه')
    for branch in Branch.objects.filter(country__isnull=True).iterator():
        name=(branch.name or '').lower()
        branch.country_id=turkey.pk if any(token in name for token in turkey_tokens) else iran.pk
        branch.save(update_fields=['country'])

    branches={b.pk:b.country_id for b in Branch.objects.only('pk','country_id')}
    for profile in EmployeeProfile.objects.filter(country__isnull=True).iterator():
        profile.country_id=branches.get(profile.branch_id) or iran.pk
        if profile.country_id==turkey.pk:
            profile.preferred_language='tr'
        profile.save(update_fields=['country','preferred_language'])

    for lead in ReferralLead.objects.filter(country__isnull=True).iterator():
        source=(lead.source_url or '').lower()
        notes=(lead.notes or '').lower()
        is_turkey=('/tr/network/' in source or '[market:turkey]' in notes or 'türkiye network' in notes)
        lead.country_id=turkey.pk if is_turkey else iran.pk
        lead.preferred_language='tr' if is_turkey else (lead.preferred_language or 'fa')
        lead.save(update_fields=['country','preferred_language'])


def unseed_country_engine(apps, schema_editor):
    # Data ownership is intentionally preserved on reverse migrations.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0058_device_booking_operational_statuses'),
    ]

    operations = [
        migrations.CreateModel(
            name='Country',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_index=True, max_length=2, unique=True)),
                ('name_english', models.CharField(max_length=80)),
                ('name_local', models.CharField(max_length=80)),
                ('flag_emoji', models.CharField(blank=True, max_length=8)),
                ('primary_language', models.CharField(choices=[('fa','فارسی'),('tr','Türkçe'),('en','English'),('ar','العربية')], default='fa', max_length=5)),
                ('secondary_language', models.CharField(blank=True, choices=[('fa','فارسی'),('tr','Türkçe'),('en','English'),('ar','العربية')], max_length=5)),
                ('currency_code', models.CharField(default='IRR', max_length=3)),
                ('currency_symbol', models.CharField(blank=True, max_length=12)),
                ('timezone', models.CharField(default='Asia/Tehran', max_length=64)),
                ('phone_prefix', models.CharField(blank=True, max_length=8)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('sort_order', models.PositiveSmallIntegerField(default=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering':['sort_order','name_english','code']},
        ),
        migrations.AddField(
            model_name='branch',
            name='country',
            field=models.ForeignKey(blank=True, default=core.models.default_country_pk, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='branches', to='core.country'),
        ),
        migrations.AddField(
            model_name='employeeprofile',
            name='country',
            field=models.ForeignKey(blank=True, default=core.models.default_country_pk, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='staff', to='core.country'),
        ),
        migrations.AddField(
            model_name='employeeprofile',
            name='preferred_language',
            field=models.CharField(choices=[('fa','فارسی'),('tr','Türkçe'),('en','English'),('ar','العربية')], default='fa', max_length=5),
        ),
        migrations.AddField(
            model_name='referrallead',
            name='country',
            field=models.ForeignKey(blank=True, default=core.models.default_country_pk, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='referral_leads', to='core.country'),
        ),
        migrations.AddField(
            model_name='referrallead',
            name='preferred_language',
            field=models.CharField(choices=[('fa','فارسی'),('tr','Türkçe'),('en','English'),('ar','العربية')], default='fa', max_length=5),
        ),
        migrations.RunPython(seed_country_engine, unseed_country_engine),
    ]
