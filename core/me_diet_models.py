from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class MeMealReport(models.Model):
    member = models.ForeignKey('core.CustomerPortalMember', on_delete=models.CASCADE, related_name='me_meals')
    patient = models.ForeignKey('core.PatientProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name='me_meal_reports')
    program = models.ForeignKey('core.PatientDietProgram', on_delete=models.SET_NULL, null=True, blank=True, related_name='me_meal_reports')
    adherence_percent = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    day = models.DateField(db_index=True)
    meal_key = models.CharField(max_length=80)
    label = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=[('reported','گزارش ثبت شده'),('planned','طبق برنامه'),('partial','بخشی انجام شد'),('replacement','جایگزین خوردم'),('skipped','مصرف نکردم'),('help','نیاز به کمک دارم')])
    note = models.CharField(max_length=200, blank=True)
    revision = models.PositiveIntegerField(default=1)
    food_table = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['member','day','meal_key'], name='me_meal_member_day_key'), models.CheckConstraint(condition=models.Q(adherence_percent__isnull=True) | models.Q(adherence_percent__gte=0, adherence_percent__lte=100), name='me_meal_adherence_range')]
