from datetime import timedelta, time
from decimal import Decimal
from django.contrib.auth.models import User
from django.utils import timezone
from .models import (
    CampSite, CampMembership, CampPurchaseRequest, CampInvoice, CampInventoryItem,
    CampWorker, CampWorkerAttendance, CampProject, CampDailyTask, CampFoodPlan, CampDailyPhoto
)

def seed_camp_demo(owner=None):
    today=timezone.localdate()
    site,_=CampSite.objects.get_or_create(name='کمپ گرین‌لایف',defaults={
        'location':'GreenLife Camp','owner_approval_threshold':5000000,'daily_photo_deadline':time(18,0)
    })
    if owner:
        CampMembership.objects.update_or_create(site=site,user=owner,defaults={'role':'owner','is_active':True})

    inventory_defaults=[
        ('برنج','food',18,'kg',25,30),('مرغ','food',12,'kg',8,15),('تخم‌مرغ','food',48,'item',30,60),
        ('روغن','food',9,'liter',6,8),('سیب‌زمینی','food',22,'kg',15,20),('پیاز','food',14,'kg',12,16),
        ('حبوبات','food',9,'kg',7,8),('چای','food',4,'kg',2,2),('قند','food',6,'kg',4,4),
        ('شوینده','cleaning',3,'pack',5,4),('سیمان','material',35,'bag',20,25),('گچ','material',9,'bag',12,15),
        ('ابزار مصرفی','tool',7,'item',4,3),('سوخت','fuel',65,'liter',40,50)
    ]
    for name,cat,stock,unit,min_stock,weekly in inventory_defaults:
        CampInventoryItem.objects.update_or_create(site=site,name=name,defaults={
            'category':cat,'current_stock':stock,'unit':unit,'minimum_stock':min_stock,
            'weekly_average_consumption':weekly,'last_purchase_date':today-timedelta(days=3),'is_active':True})

    projects=[
        ('دیوار سنگی پارکینگ','حسن رضایی',62,85000000,53000000,0),
        ('محوطه‌سازی ورودی','مهدی کریمی',38,120000000,47000000,1),
        ('کافه طبقه چهارم','علی یوسفی',28,180000000,64000000,5),
        ('سرویس بهداشتی طبقه چهارم','حسن رضایی',74,95000000,101000000,2),
        ('مسیر سلامت','مهدی کریمی',16,70000000,12000000,7),
    ]
    project_objs=[]
    for name,manager,progress,estimate,actual,days_ago in projects:
        obj,_=CampProject.objects.update_or_create(site=site,name=name,defaults={
            'manager':manager,'start_date':today-timedelta(days=35),'status':'active','progress':progress,
            'estimated_cost':estimate,'actual_cost':actual,'last_progress_date':today-timedelta(days=days_ago),
            'description':'پروژه نمونه برای تست کامل ماژول Camp.'})
        project_objs.append(obj)

    workers=[
        ('حسن رضایی','foreman','09120000001',1800000),('مهدی کریمی','mason','09120000002',1600000),
        ('رضا احمدی','laborer','09120000003',1100000),('مجتبی نوروزی','laborer','09120000004',1100000),
        ('کاظم شریفی','guard','09120000005',1200000),('اکبر محمدی','gardener','09120000006',1150000),
        ('سعید مرادی','driver','09120000007',1400000),('جواد اکبری','cook','09120000008',1300000),
    ]
    worker_objs=[]
    for name,role,phone,wage in workers:
        w,_=CampWorker.objects.update_or_create(site=site,full_name=name,defaults={
            'role':role,'phone':phone,'status':'active','daily_wage':wage,'referral':'GreenLife'})
        worker_objs.append(w)
    for i,w in enumerate(worker_objs):
        if i<7:
            CampWorkerAttendance.objects.update_or_create(worker=w,date=today,defaults={
                'is_present':True,'start_time':time(8,0+i%2*15),'end_time':None,
                'work_done':'فعالیت روزانه کمپ','wage_for_day':w.daily_wage,'created_by':owner})

    task_titles=[
        ('ادامه دیوار سنگی پارکینگ','حسن رضایی','urgent',project_objs[0],'doing'),
        ('جمع‌آوری نخاله‌ها','رضا احمدی','important',project_objs[1],'todo'),
        ('خرید مواد غذایی','سعید مرادی','important',None,'done'),
        ('آبیاری گیاهان','اکبر محمدی','normal',project_objs[1],'done'),
        ('تمیزکاری طبقه چهارم','مجتبی نوروزی','normal',project_objs[2],'doing'),
        ('بررسی موجودی انبار','حسن رضایی','important',None,'done'),
        ('ارسال عکس روزانه','مهدی کریمی','urgent',None,'todo'),
    ]
    for title,responsible,priority,project,status in task_titles:
        CampDailyTask.objects.update_or_create(site=site,date=today,title=title,defaults={
            'responsible':responsible,'priority':priority,'project':project,'status':status,
            'description':'وظیفه نمونه روزانه','created_by':owner})

    purchases=[
        ('برنج','food',25,'kg',4200000,'خرید هفتگی غذا','important','pending'),
        ('سیمان','material',20,'bag',7600000,'ادامه دیوار سنگی','urgent','pending'),
        ('دستکش کار','tool',12,'item',1800000,'ایمنی کارگرها','normal','approved'),
        ('گازوئیل','fuel',60,'liter',2100000,'سوخت تجهیزات','important','purchased'),
    ]
    for item,cat,qty,unit,amount,reason,urgency,status in purchases:
        p,_=CampPurchaseRequest.objects.update_or_create(site=site,item_name=item,request_date=today,defaults={
            'category':cat,'quantity':qty,'unit':unit,'estimated_amount':amount,'reason':reason,
            'requester':owner,'urgency':urgency,'status':status})
        if item=='دستکش کار':
            CampInvoice.objects.update_or_create(purchase=p,defaults={
                'final_amount':1950000,'vendor':'فروشگاه ابزار','payment_method':'card','is_paid':False,'created_by':owner})

    meals=[
        (today-timedelta(days=3),'پلو مرغ',8,'برنج، مرغ، روغن، پیاز',950000),
        (today-timedelta(days=2),'املت و سیب‌زمینی',8,'تخم‌مرغ، گوجه، سیب‌زمینی',420000),
        (today-timedelta(days=1),'عدس‌پلو',7,'برنج، عدس، پیاز',560000),
        (today,'کتلت و نان',7,'سیب‌زمینی، تخم‌مرغ، گوشت، نان',610000),
        (today+timedelta(days=1),'لوبیا',8,'لوبیا، سیب‌زمینی، نان',0),
        (today+timedelta(days=2),'تخم‌مرغ و سیب‌زمینی',8,'تخم‌مرغ، سیب‌زمینی، نان',0),
        (today+timedelta(days=3),'عدسی و نان',8,'عدس، پیاز، نان',0),
    ]
    for d,meal,count,ingredients,cost in meals:
        CampFoodPlan.objects.update_or_create(site=site,date=d,defaults={
            'meal':meal,'people_count':count,'ingredients':ingredients,'estimated_cost':cost or 550000,
            'actual_cost':cost,'responsible':'جواد اکبری'})

    for photo_type,caption,location,project in [
        ('project','پیشرفت امروز دیوار سنگی','پارکینگ',project_objs[0]),
        ('work','جمع‌آوری و مرتب‌سازی محوطه','ورودی',project_objs[1]),
        ('site','نمای کلی کمپ در پایان شیفت','محوطه اصلی',None),
    ]:
        CampDailyPhoto.objects.get_or_create(site=site,date=today,photo_type=photo_type,caption=caption,defaults={
            'image':'camp/demo/camp-day.jpg','uploader':owner,'project':project,'location':location})

    return site
