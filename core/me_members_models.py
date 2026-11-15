"""Member care state and auditable, non-monetary encouragement points."""
from django.db import models
from django.conf import settings

class MeMemberCare(models.Model):
    member=models.OneToOneField('core.CustomerPortalMember',on_delete=models.CASCADE,related_name='me_care')
    assigned_to=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='me_member_cases')
    followup_at=models.DateTimeField(null=True,blank=True)
    reviewed_at=models.DateTimeField(null=True,blank=True)
    revision=models.PositiveIntegerField(default=0)
    updated_at=models.DateTimeField(auto_now=True)

class MeMemberAction(models.Model):
    KINDS=[('reply','پاسخ به عضو'),('note','یادداشت داخلی'),('points','امتیاز تشویقی'),('followup','تنظیم پیگیری'),('review','بررسی شد')]
    member=models.ForeignKey('core.CustomerPortalMember',on_delete=models.CASCADE,related_name='me_actions')
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    kind=models.CharField(max_length=12,choices=KINDS)
    body=models.CharField(max_length=1000)
    points=models.PositiveSmallIntegerField(default=0)
    token=models.UUIDField(unique=True)
    created_at=models.DateTimeField(auto_now_add=True,db_index=True)
    class Meta:
        ordering=['-created_at','-pk']
        constraints=[models.CheckConstraint(condition=(models.Q(kind='points',points__gte=1,points__lte=100)|(~models.Q(kind='points')&models.Q(points=0))),name='me_member_points_valid')]
