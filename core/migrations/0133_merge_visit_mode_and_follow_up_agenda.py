"""Merge concurrent appointment visit mode and callback agenda migrations.

Both 0132 migrations depend on 0131 and touch separate tables/columns.
This explicit dependency merger is intentionally operations-free.
"""
from django.db import migrations

class Migration(migrations.Migration):
    dependencies=[
        ("core","0132_call_center_follow_up_agenda"),
        ("core","0132_visitappointment_visit_mode"),
    ]
    operations=[]
