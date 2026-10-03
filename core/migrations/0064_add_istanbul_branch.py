from django.db import migrations


def add_istanbul_branch(apps, schema_editor):
    Country = apps.get_model('core', 'Country')
    Branch = apps.get_model('core', 'Branch')

    turkey = Country.objects.filter(code='TR').first()
    if not turkey:
        return

    aliases = ['استانبول', 'Istanbul', 'İstanbul']
    branch = Branch.objects.filter(name__in=aliases).first()

    if branch:
        changed = []
        if branch.name != 'استانبول':
            branch.name = 'استانبول'
            changed.append('name')
        if branch.country_id != turkey.pk:
            branch.country_id = turkey.pk
            changed.append('country')
        if not branch.is_active:
            branch.is_active = True
            changed.append('is_active')
        if changed:
            branch.save(update_fields=changed)
    else:
        Branch.objects.create(
            name='استانبول',
            country=turkey,
            is_active=True,
        )


def noop_reverse(apps, schema_editor):
    # Keep operational branch data on rollback.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0063_whatsapp_hub_premium'),
    ]

    operations = [
        migrations.RunPython(add_istanbul_branch, noop_reverse),
    ]
