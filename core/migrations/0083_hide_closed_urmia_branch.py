from django.db import migrations
from django.db.models import Q


def deactivate_closed_urmia_branch(apps, schema_editor):
    """Hide the closed location from active operational pickers; retain all history.

    This flag can be turned back on through branch administration if the owner
    later authorizes reopening. Nothing is deleted or reassigned.
    """
    Branch = apps.get_model("core", "Branch")
    names = (
        Q(name__icontains="ارومیه")
        | Q(name__icontains="اروميه")
        | Q(name__icontains="urmia")
        | Q(name__icontains="orumi")
    )
    Branch.objects.filter(names).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("core", "0082_bulk_sms_campaigns")]
    operations = [
        migrations.RunPython(
            deactivate_closed_urmia_branch,
            migrations.RunPython.noop,
        ),
    ]
