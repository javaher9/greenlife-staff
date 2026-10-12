from django.db import migrations, models


def preserve_existing_device_prices(apps, schema_editor):
    """Copy only unambiguous legacy prices; keep conflicting prices as fallbacks."""
    Type = apps.get_model("core", "DeviceTypeSchedule")
    Catalog = apps.get_model("core", "TreatmentCatalogItem")
    alias = schema_editor.connection.alias
    for device_type in Type.objects.using(alias).all().iterator():
        name = device_type.name.casefold()
        if any(token in name for token in ("cryo", "کرایو", "cooltech", "کول تک", "کولتک")):
            device_type.price_unit = "cup"
        historic_prices = set(Catalog.objects.using(alias).filter(
            category="device", name__iexact=device_type.name, is_active=True,
            price_toman__isnull=False,
        ).values_list("price_toman", flat=True))
        if len(historic_prices) == 1:
            device_type.unit_price_toman = historic_prices.pop()
        device_type.save(update_fields=["price_unit", "unit_price_toman"])


class Migration(migrations.Migration):
    dependencies = [("core", "0084_seed_treatment_service_master_data")]
    operations = [
        migrations.AddField(
            model_name="devicetypeschedule", name="unit_price_toman",
            field=models.DecimalField(max_digits=18,decimal_places=0,null=True,blank=True),
        ),
        migrations.AddField(
            model_name="devicetypeschedule", name="price_unit",
            field=models.CharField(max_length=12,default="session",choices=[
                ("session","جلسه"),("cup","کاپ")
            ]),
        ),
        migrations.RunPython(preserve_existing_device_prices,migrations.RunPython.noop),
    ]
