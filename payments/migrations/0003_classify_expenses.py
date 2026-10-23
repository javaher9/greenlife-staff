from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('payments', '0002_clarification')]

    operations = [
        migrations.AddField(model_name='paymentrequest', name='category', field=models.CharField(max_length=24, choices=[['unspecified','دسته‌بندی‌نشده'],['legal','وکیل و امور حقوقی'],['salaries','حقوق و مزایا'],['commission','پورسانت'],['advertising','تبلیغات و بازاریابی'],['equipment','تجهیزات و دستگاه‌ها'],['supplies','خرید و ملزومات'],['rent','اجاره و ساختمان'],['utilities','آب، برق و خدمات'],['transport','حمل‌ونقل و سفر'],['projects','پروژه و سرمایه‌گذاری'],['personal','هزینه شخصی'],['other','سایر']], default='unspecified', db_index=True)),
        migrations.AddField(model_name='paymentrequest', name='cost_owner', field=models.CharField(max_length=20, choices=[['unspecified','تعیین‌نشده'],['company','شرکت'],['personal','شخصی مدیر'],['project','پروژه'],['other','سایر / خارج از شرکت']], default='unspecified', db_index=True)),
        migrations.AddField(model_name='paymentrequest', name='cost_center', field=models.CharField(max_length=160, blank=True)),
        migrations.AddField(model_name='pettycashexpense', name='category', field=models.CharField(max_length=24, choices=[['unspecified','دسته‌بندی‌نشده'],['legal','وکیل و امور حقوقی'],['salaries','حقوق و مزایا'],['commission','پورسانت'],['advertising','تبلیغات و بازاریابی'],['equipment','تجهیزات و دستگاه‌ها'],['supplies','خرید و ملزومات'],['rent','اجاره و ساختمان'],['utilities','آب، برق و خدمات'],['transport','حمل‌ونقل و سفر'],['projects','پروژه و سرمایه‌گذاری'],['personal','هزینه شخصی'],['other','سایر']], default='unspecified', db_index=True)),
        migrations.AddField(model_name='pettycashexpense', name='cost_owner', field=models.CharField(max_length=20, choices=[['unspecified','تعیین‌نشده'],['company','شرکت'],['personal','شخصی مدیر'],['project','پروژه'],['other','سایر / خارج از شرکت']], default='unspecified', db_index=True)),
        migrations.AddField(model_name='pettycashexpense', name='cost_center', field=models.CharField(max_length=160, blank=True)),
        migrations.AddField(model_name='paymentrequest', name='due_date', field=models.DateField(null=True, blank=True)),
    ]
