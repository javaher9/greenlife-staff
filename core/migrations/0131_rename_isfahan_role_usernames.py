"""Rename Isfahan fixed-role usernames without changing user IDs or history."""

from django.db import migrations


RENAMES=(
    ("esfahan.reception","Esfehan.monshi","receptionist"),
    ("esfahan.consultant","Esfehan.moshaver","consultant"),
)


def rename_role_accounts(apps,schema_editor):
    User=apps.get_model("auth","User")
    Profile=apps.get_model("core","EmployeeProfile")
    db=schema_editor.connection.alias
    for old,new,role in RENAMES:
        original=list(User.objects.using(db).filter(username__iexact=old))
        destination=list(User.objects.using(db).filter(username__iexact=new))
        if not original:
            if len(destination)==1:
                continue  # Already renamed by a permitted administrator.
            # Django's *ephemeral test database* has no production staff user
            # accounts. This safety exception never applies to the live DB:
            # production continues to refuse silent missing-account renames.
            database_name=str(schema_editor.connection.settings_dict.get("NAME") or "")
            if not destination and database_name.startswith("test_"):
                continue
            raise RuntimeError(f"{old}: account missing; preserving database unchanged")
        if len(original)!=1 or destination:
            raise RuntimeError(f"{old}: conflicting accounts; preserving database unchanged")
        user=original[0]
        profile=Profile.objects.using(db).filter(user_id=user.pk).first()
        if not profile or profile.role!=role or user.is_superuser or user.is_staff:
            raise RuntimeError(f"{old}: unexpected account identity/role; refusing rename")
        user.username=new
        user.save(using=db,update_fields=["username"])


class Migration(migrations.Migration):
    dependencies=[("core","0130_memembercare_mememberaction")]
    operations=[migrations.RunPython(rename_role_accounts,migrations.RunPython.noop)]
