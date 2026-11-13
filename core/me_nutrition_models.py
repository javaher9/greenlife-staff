from django.db import models


class MeNutritionProgress(models.Model):
    member = models.OneToOneField('core.CustomerPortalMember', on_delete=models.CASCADE, related_name='nutrition_progress')
    choices = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)
