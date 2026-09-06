from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ('core','0030_visit_appointment'),
    ]

    operations=[
        migrations.CreateModel(
            name='InternalConversation',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('title',models.CharField(blank=True,max_length=160)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('updated_at',models.DateTimeField(auto_now=True,db_index=True)),
                ('created_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='created_internal_conversations',to=settings.AUTH_USER_MODEL)),
                ('participants',models.ManyToManyField(related_name='internal_conversations',to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['-updated_at','-id']},
        ),
        migrations.CreateModel(
            name='InternalMessage',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('body',models.TextField()),
                ('created_at',models.DateTimeField(auto_now_add=True,db_index=True)),
                ('conversation',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='messages',to='core.internalconversation')),
                ('read_by',models.ManyToManyField(blank=True,related_name='read_internal_messages',to=settings.AUTH_USER_MODEL)),
                ('sender',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='sent_internal_messages',to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['created_at','id']},
        ),
        migrations.AddIndex(
            model_name='internalmessage',
            index=models.Index(fields=['conversation','created_at'],name='imsg_conv_created_idx'),
        ),
    ]
