"""Structured callback time and immutable audit trail for lead follow-ups."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("core","0131_rename_isfahan_role_usernames"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations=[
        migrations.AddField(
            model_name="referrallead",
            name="next_follow_up_time",
            field=models.TimeField(blank=True,null=True,help_text="ساعت تماس وعده داده‌شده؛ برای موعدهای قدیمی ممکن است ثبت نشده باشد."),
        ),
        migrations.CreateModel(
            name="LeadFollowUpLog",
            fields=[
                ("id",models.BigAutoField(primary_key=True,serialize=False)),
                ("action",models.CharField(max_length=20,choices=[
                    ("scheduled","ثبت موعد"),("attempt","تلاش برای تماس"),
                    ("closed","پایان پیگیری"),("updated","ویرایش پیگیری"),
                ])),
                ("result",models.CharField(max_length=20,blank=True)),
                ("previous_date",models.DateField(null=True,blank=True)),
                ("previous_time",models.TimeField(null=True,blank=True)),
                ("scheduled_for",models.DateField(null=True,blank=True)),
                ("scheduled_time",models.TimeField(null=True,blank=True)),
                ("note",models.TextField(blank=True)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("actor",models.ForeignKey(to=settings.AUTH_USER_MODEL,on_delete=django.db.models.deletion.SET_NULL,null=True,blank=True,related_name="lead_follow_up_actions")),
                ("lead",models.ForeignKey(to="core.referrallead",on_delete=django.db.models.deletion.CASCADE,related_name="follow_up_history")),
            ],
            options={"ordering":["-created_at","-pk"]},
        ),
        migrations.AddIndex(
            model_name="leadfollowuplog",
            index=models.Index(fields=["lead","-created_at"],name="leadfollow_history_idx"),
        ),
        migrations.AddIndex(
            model_name="leadfollowuplog",
            index=models.Index(fields=["actor","-created_at"],name="leadfollow_actor_idx"),
        ),
    ]
