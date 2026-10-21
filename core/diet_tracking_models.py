"""Patient-reported execution, isolated by prescription and weekly cycle."""
from django.db import models
from django.utils import timezone

class DietMealCheckin(models.Model):
    STATUS=[('planned','طبق برنامه'),('replacement','جایگزین'),('partial','بخشی از وعده'),('skipped','وعده مصرف نشده')]
    program=models.ForeignKey('core.PatientDietProgram',on_delete=models.CASCADE,related_name='meal_checkins')
    cycle=models.PositiveIntegerField(default=0)
    day=models.PositiveSmallIntegerField()
    meal_key=models.CharField(max_length=32)
    meal_label=models.CharField(max_length=200)
    status=models.CharField(max_length=16,choices=STATUS)
    note=models.CharField(max_length=600,blank=True)
    reported_on=models.DateField(default=timezone.localdate,db_index=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True,db_index=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['program','cycle','day','meal_key'],name='diet_unique_meal_checkin')]

class DietFoodChange(models.Model):
    program=models.ForeignKey('core.PatientDietProgram',on_delete=models.CASCADE,related_name='food_changes')
    day=models.PositiveSmallIntegerField()
    food=models.CharField(max_length=400)
    amount=models.CharField(max_length=120,blank=True)
    reason=models.CharField(max_length=20,blank=True,choices=[('hunger','گرسنگی'),('craving','هوس'),('party','مهمانی'),('stress','استرس'),('other','دلیل دیگر')])
    reported_on=models.DateField(default=timezone.localdate,db_index=True)
    created_at=models.DateTimeField(auto_now_add=True)
    request_id=models.UUIDField()
    class Meta:
        constraints=[models.UniqueConstraint(fields=['program','request_id'],name='diet_unique_change_request')]
