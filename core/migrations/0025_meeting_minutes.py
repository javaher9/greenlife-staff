import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core','0024_finance_receipt_analysis'),
    ]
    operations=[
        migrations.CreateModel(
            name='MeetingMinute',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('title',models.CharField(max_length=200)),
                ('meeting_date',models.DateField(db_index=True,default=django.utils.timezone.localdate)),
                ('start_time',models.TimeField(blank=True,null=True)),
                ('location',models.CharField(blank=True,max_length=160)),
                ('summary',models.TextField(blank=True)),
                ('status',models.CharField(choices=[('open','باز'),('closed','بسته‌شده')],db_index=True,default='open',max_length=20)),
                ('closed_at',models.DateTimeField(blank=True,null=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('attendees',models.ManyToManyField(blank=True,related_name='attended_meeting_minutes',to=settings.AUTH_USER_MODEL)),
                ('created_by',models.ForeignKey(null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='created_meeting_minutes',to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['-meeting_date','-created_at']},
        ),
        migrations.CreateModel(
            name='MeetingActionItem',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('title',models.CharField(max_length=220)),
                ('description',models.TextField(blank=True)),
                ('due_date',models.DateField(blank=True,db_index=True,null=True)),
                ('priority',models.CharField(choices=[('normal','عادی'),('high','مهم'),('urgent','فوری')],default='normal',max_length=20)),
                ('status',models.CharField(choices=[('todo','انجام‌نشده'),('doing','در حال انجام'),('awaiting_approval','منتظر تأیید'),('done','انجام‌شده'),('blocked','متوقف')],db_index=True,default='todo',max_length=24)),
                ('completion_note',models.TextField(blank=True)),
                ('approved_at',models.DateTimeField(blank=True,null=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('approved_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='approved_meeting_actions',to=settings.AUTH_USER_MODEL)),
                ('assigned_to',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='assigned_meeting_actions',to=settings.AUTH_USER_MODEL)),
                ('collaborators',models.ManyToManyField(blank=True,related_name='collaborating_meeting_actions',to=settings.AUTH_USER_MODEL)),
                ('meeting',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='action_items',to='core.meetingminute')),
                ('task',models.OneToOneField(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='meeting_action',to='core.task')),
            ],
            options={'ordering':['status','due_date','-priority','id']},
        ),
        migrations.CreateModel(
            name='MeetingActionStep',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('title',models.CharField(max_length=180)),
                ('is_done',models.BooleanField(default=False)),
                ('sort_order',models.PositiveSmallIntegerField(default=0)),
                ('completed_at',models.DateTimeField(blank=True,null=True)),
                ('action',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='steps',to='core.meetingactionitem')),
                ('completed_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='completed_meeting_steps',to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['sort_order','id']},
        ),
        migrations.CreateModel(
            name='MeetingActionUpdate',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('previous_status',models.CharField(blank=True,max_length=24)),
                ('new_status',models.CharField(choices=[('todo','انجام‌نشده'),('doing','در حال انجام'),('awaiting_approval','منتظر تأیید'),('done','انجام‌شده'),('blocked','متوقف')],max_length=24)),
                ('note',models.TextField(blank=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('action',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='updates',to='core.meetingactionitem')),
                ('user',models.ForeignKey(null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='meeting_action_updates',to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['-created_at']},
        ),
    ]
