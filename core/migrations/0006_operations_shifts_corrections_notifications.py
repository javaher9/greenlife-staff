from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[('core','0005_finance_crm')]
    operations=[
        migrations.CreateModel(name='WorkShift',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('name',models.CharField(max_length=100)),('start_time',models.TimeField()),('end_time',models.TimeField()),('grace_minutes',models.PositiveSmallIntegerField(default=15)),('report_required',models.BooleanField(default=True)),('is_active',models.BooleanField(default=True)),
            ('branch',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='work_shifts',to='core.branch'))]),
        migrations.CreateModel(name='ShiftAssignment',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('date',models.DateField()),('note',models.CharField(blank=True,max_length=250)),('created_at',models.DateTimeField(auto_now_add=True)),
            ('created_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='created_shift_assignments',to='auth.user')),('shift',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='assignments',to='core.workshift')),('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='shift_assignments',to='auth.user'))],options={'ordering':['-date','user__last_name']}),
        migrations.AddConstraint(model_name='shiftassignment',constraint=models.UniqueConstraint(fields=('user','date'),name='uniq_shift_user_date')),
        migrations.CreateModel(name='AttendanceCorrectionRequest',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('date',models.DateField()),('requested_check_in',models.DateTimeField(blank=True,null=True)),('requested_check_out',models.DateTimeField(blank=True,null=True)),('reason',models.TextField()),('status',models.CharField(choices=[('pending','در انتظار بررسی'),('approved','تایید شده'),('rejected','رد شده')],default='pending',max_length=20)),('manager_note',models.TextField(blank=True)),('created_at',models.DateTimeField(auto_now_add=True)),('reviewed_at',models.DateTimeField(blank=True,null=True)),
            ('attendance',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='correction_requests',to='core.attendance')),('reviewed_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='reviewed_attendance_corrections',to='auth.user')),('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='attendance_corrections',to='auth.user'))],options={'ordering':['-created_at']}),
        migrations.CreateModel(name='StaffNotification',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('title',models.CharField(max_length=160)),('message',models.TextField()),('notification_type',models.CharField(default='info',max_length=40)),('related_date',models.DateField(blank=True,null=True)),('is_read',models.BooleanField(default=False)),('created_at',models.DateTimeField(auto_now_add=True)),('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='staff_notifications',to='auth.user'))],options={'ordering':['-created_at']})]
