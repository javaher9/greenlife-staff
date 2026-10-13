from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies=[('core','0088_daily_diet_presentation')]
    operations=[
        migrations.AlterField(
            model_name='treatmentrichsection',name='meal_slot',
            field=models.CharField(
                max_length=16,default='other',
                choices=[
                    ('other','بخش عمومی'),('fasting','ناشتا'),
                    ('breakfast','صبحانه'),('snack_am','میان‌وعده صبح'),
                    ('lunch','ناهار'),('snack_pm','عصرانه'),('dinner','شام'),
                ],
            ),
        ),
    ]
