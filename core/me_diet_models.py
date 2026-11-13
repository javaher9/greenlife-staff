from django.db import models


class MeMealReport(models.Model):
    member = models.ForeignKey('core.CustomerPortalMember', on_delete=models.CASCADE, related_name='me_meals')
    day = models.DateField(db_index=True)
    meal_key = models.CharField(max_length=80)
    label = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=[('planned','طبق برنامه'),('partial','بخشی انجام شد'),('replacement','جایگزین خوردم'),('skipped','مصرف نکردم'),('help','نیاز به کمک دارم')])
    note = models.CharField(max_length=200, blank=True)
    revision = models.PositiveIntegerField(default=1)
    food_table = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['member','day','meal_key'], name='me_meal_member_day_key')]
