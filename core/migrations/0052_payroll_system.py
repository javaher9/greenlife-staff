from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0051_treatment_catalog_item'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PayrollRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('base_salary_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('commission_percent', models.DecimalField(decimal_places=3, default=0, max_digits=7)),
                ('commission_source', models.CharField(choices=[('auto', 'خودکار بر اساس نقش'), ('call_center', 'فروش منتسب کال‌سنتر'), ('recorded_sale', 'فروش ثبت‌شده توسط فرد'), ('none', 'بدون پورسانت')], default='auto', max_length=20)),
                ('note', models.CharField(blank=True, max_length=500)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('profile', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='payroll_rule', to='core.employeeprofile')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='updated_payroll_rules', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['profile__branch__name', 'profile__user__last_name', 'profile__user__first_name']},
        ),
        migrations.CreateModel(
            name='PayrollMonthlyAdjustment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month_start', models.DateField(db_index=True, help_text='روز اول ماه شمسی، ذخیره‌شده به تاریخ میلادی')),
                ('mission_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('returned_sales_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('absence_deduction_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('late_deduction_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('bonus_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('salary_deduction_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('advance_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('insurance_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('note', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payroll_adjustments', to='core.employeeprofile')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='updated_payroll_adjustments', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-month_start', 'profile__user__last_name']},
        ),
        migrations.CreateModel(
            name='PayrollSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month_start', models.DateField(db_index=True)),
                ('base_salary_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('sales_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('returned_sales_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('commission_percent', models.DecimalField(decimal_places=3, default=0, max_digits=7)),
                ('commission_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('mission_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('bonus_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('absence_count', models.PositiveIntegerField(default=0)),
                ('late_count', models.PositiveIntegerField(default=0)),
                ('absence_deduction_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('late_deduction_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('salary_deduction_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('advance_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('insurance_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('net_salary_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('closed_at', models.DateTimeField(auto_now_add=True)),
                ('closed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='closed_payroll_snapshots', to=settings.AUTH_USER_MODEL)),
                ('profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payroll_snapshots', to='core.employeeprofile')),
            ],
            options={'ordering': ['-month_start', 'profile__user__last_name']},
        ),
        migrations.AddConstraint(
            model_name='payrollmonthlyadjustment',
            constraint=models.UniqueConstraint(fields=('profile', 'month_start'), name='uniq_payroll_adjustment_profile_month'),
        ),
        migrations.AddConstraint(
            model_name='payrollsnapshot',
            constraint=models.UniqueConstraint(fields=('profile', 'month_start'), name='uniq_payroll_snapshot_profile_month'),
        ),
    ]
