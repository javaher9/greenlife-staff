from django.db import migrations, models
import django.db.models.deletion


def backfill_member_countries(apps, schema_editor):
    Country=apps.get_model('core','Country')
    PublicNetworkMember=apps.get_model('public_network','PublicNetworkMember')
    iran=Country.objects.get(code='IR')
    turkey=Country.objects.get(code='TR')
    for member in PublicNetworkMember.objects.filter(country__isnull=True).iterator():
        source=(member.source_url or '').lower()
        is_turkey='/tr/network/' in source
        member.country_id=turkey.pk if is_turkey else iran.pk
        member.preferred_language='tr' if is_turkey else 'fa'
        member.save(update_fields=['country','preferred_language'])


class Migration(migrations.Migration):

    dependencies=[
        ('core','0059_country_engine'),
        ('public_network','0001_initial'),
    ]

    operations=[
        migrations.AddField(
            model_name='publicnetworkmember',
            name='country',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='public_network_members', to='core.country'),
        ),
        migrations.AddField(
            model_name='publicnetworkmember',
            name='preferred_language',
            field=models.CharField(choices=[('fa','فارسی'),('tr','Türkçe'),('en','English'),('ar','العربية')], default='fa', max_length=5),
        ),
        migrations.RunPython(backfill_member_countries, migrations.RunPython.noop),
    ]
