from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ('core','0030_visit_appointment'),
    ]

    operations=[
        migrations.CreateModel(
            name='InternalMessage',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('body',models.TextField(max_length=2000)),
                ('read_at',models.DateTimeField(blank=True,null=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('recipient',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.CASCADE,related_name='received_internal_messages',to=settings.AUTH_USER_MODEL)),
                ('sender',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='sent_internal_messages',to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['created_at','id']},
        ),
        migrations.AddIndex(
            model_name='internalmessage',
            index=models.Index(fields=['recipient','read_at','-created_at'],name='imsg_rec_read_created_idx'),
        ),
        migrations.AddIndex(
            model_name='internalmessage',
            index=models.Index(fields=['sender','recipient','-created_at'],name='imsg_pair_created_idx'),
        ),
    ]
