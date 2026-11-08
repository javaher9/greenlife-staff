import secrets
import string
from django.db import migrations, models
import core.sms_interest_models


ALPHABET = string.ascii_letters + string.digits


def add_codes(apps, schema_editor):
    Invitation = apps.get_model('core', 'SmsInterestInvitation')
    used = set()
    for item in Invitation.objects.all().iterator():
        code = ''
        while not code or code in used:
            code = ''.join(secrets.choice(ALPHABET) for _ in range(7))
        used.add(code)
        item.short_code = code
        item.save(update_fields=['short_code'])


class Migration(migrations.Migration):
    dependencies = [('core', '0115_sms_interest_invitation')]
    operations = [
        migrations.AddField(model_name='smsinterestinvitation', name='short_code', field=models.CharField(blank=True, max_length=7, null=True)),
        migrations.RunPython(add_codes, migrations.RunPython.noop),
        migrations.AlterField(model_name='smsinterestinvitation', name='short_code', field=models.CharField(db_index=True, default=core.sms_interest_models.sms_interest_short_code, editable=False, max_length=7, unique=True)),
    ]
