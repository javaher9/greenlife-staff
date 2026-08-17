from datetime import timedelta
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .jalali import format_jalali, parse_jalali
from .models import (
    CampSite, CampMembership, CampPurchaseRequest, CampInvoice,
    CampInventoryItem, CampInventoryMovement, CampWorker, CampWorkerAttendance,
    CampProject, CampDailyTask, CampFoodPlan, CampDailyPhoto, CampCommanderCheck
)
from .forms import (
    CampPurchaseRequestForm, CampInvoiceForm, CampInventoryItemForm,
    CampInventoryMovementForm, CampWorkerForm, CampWorkerAttendanceForm,
    CampProjectForm, CampDailyTaskForm, CampFoodPlanForm, CampDailyPhotoForm
)


def camp_site():
    site=CampSite.objects.filter(is_active=True).first()
    if not site:
        site=CampSite.objects.create(name='کمپ گرین‌لایف')
    return site


def camp_role(user, site=None):
    site=site or camp_site()
    # Existing Staff admins are owners by default.
    profile=getattr(user,'profile',None)
    if getattr(profile,'role',None)=='admin' or user.is_superuser:
        return 'owner'
    membership=CampMembership.objects.filter(site=site,user=user,is_active=True).first()
    if membership: return membership.role
    # Simple local/mock fallback until dedicated Camp identities/API are connected.
    if getattr(profile,'role',None)=='manager': return 'supervisor'
    if getattr(profile,'role',None)=='employee': return 'worker'
    return None


def camp_required(roles=None):
    roles=set(roles or ['owner','supervisor','worker','finance'])
    def dec(view):
        @wraps(view)
        @login_required
        def wrapper(request,*args,**kwargs):
            role=camp_role(request.user)
            if role not in roles:
                messages.error(request,'دسترسی شما به این بخش Camp مجاز نیست.')
                return redirect('dashboard')
            request.camp_role=role
            request.camp_site=camp_site()
            return view(request,*args,**kwargs)
        return wrapper
    return dec


def toman(value):
    try: return f'{int(value):,}'
    except Exception: return '0'


def _today_summary(site):
    today=timezone.localdate()
    week_start=today-timedelta(days=6)
    attendance=CampWorkerAttendance.objects.filter(worker__site=site,date=today,is_present=True)
    worker_cost=attendance.aggregate(x=Sum('wage_for_day'))['x'] or 0
    food_cost=CampFoodPlan.objects.filter(site=site,date=today).aggregate(x=Sum('actual_cost'))['x'] or 0
    invoices=CampInvoice.objects.filter(purchase__site=site,created_at__date=today)
    purchase_cost=invoices.aggregate(x=Sum('final_amount'))['x'] or 0
    today_cost=worker_cost+food_cost+purchase_cost
    weekly_purchase=CampInvoice.objects.filter(purchase__site=site,created_at__date__range=(week_start,today)).aggregate(x=Sum('final_amount'))['x'] or 0
    weekly_worker=CampWorkerAttendance.objects.filter(worker__site=site,date__range=(week_start,today),is_present=True).aggregate(x=Sum('wage_for_day'))['x'] or 0
    weekly_food=CampFoodPlan.objects.filter(site=site,date__range=(week_start,today)).aggregate(x=Sum('actual_cost'))['x'] or 0
    return {
        'today':today,'present_workers':attendance.count(),'worker_cost':worker_cost,'food_cost':food_cost,
        'purchase_cost':purchase_cost,'today_cost':today_cost,'week_cost':weekly_purchase+weekly_worker+weekly_food,
        'photos':CampDailyPhoto.objects.filter(site=site,date=today).count(),
        'tasks_done':CampDailyTask.objects.filter(site=site,date=today,status='done').count(),
        'tasks_total':CampDailyTask.objects.filter(site=site,date=today).count(),
    }


def _camp_alerts(site):
    today=timezone.localdate()
    alerts=[]
    summary=_today_summary(site)

    # Unusual spend: compare today with average of previous 7 days when available.
    previous=[]
    for n in range(1,8):
        d=today-timedelta(days=n)
        worker=CampWorkerAttendance.objects.filter(worker__site=site,date=d,is_present=True).aggregate(x=Sum('wage_for_day'))['x'] or 0
        food=CampFoodPlan.objects.filter(site=site,date=d).aggregate(x=Sum('actual_cost'))['x'] or 0
        purchases=CampInvoice.objects.filter(purchase__site=site,created_at__date=d).aggregate(x=Sum('final_amount'))['x'] or 0
        previous.append(worker+food+purchases)
    nonzero=[Decimal(x) for x in previous if x]
    avg=(sum(nonzero)/len(nonzero)) if nonzero else Decimal('0')
    if avg and Decimal(summary['today_cost']) > avg*Decimal('1.35'):
        alerts.append({'level':'danger','title':'هزینه امروز بیش از حد معمول است','text':f"هزینه امروز {toman(summary['today_cost'])} تومان است؛ میانگین روزهای اخیر حدود {toman(avg)} تومان بوده."})

    for item in CampInventoryItem.objects.filter(site=site,is_active=True):
        if item.stock_status in ('low','critical'):
            alerts.append({'level':'danger' if item.stock_status=='critical' else 'warning','title':f'موجودی {item.name} کم است','text':f'{item.current_stock:g} {item.get_unit_display()} باقی مانده؛ حداقل {item.minimum_stock:g}.'})

    missing_invoice=CampPurchaseRequest.objects.filter(site=site,status__in=['purchased','paid']).filter(invoice__isnull=True)
    if missing_invoice.exists():
        alerts.append({'level':'warning','title':'خرید بدون فاکتور','text':f'{missing_invoice.count()} خرید انجام شده هنوز فاکتور ثبت‌شده ندارد.'})

    invoice_no_photo=CampInvoice.objects.filter(purchase__site=site).filter(Q(invoice_image='')|Q(invoice_image__isnull=True)).count()
    if invoice_no_photo:
        alerts.append({'level':'warning','title':'فاکتور بدون عکس','text':f'{invoice_no_photo} فاکتور عکس ندارد.'})

    now=timezone.localtime()
    if now.time() >= site.daily_photo_deadline and summary['photos']==0:
        alerts.append({'level':'danger','title':'گزارش تصویری امروز ثبت نشده است','text':f'مهلت عکس روزانه ساعت {site.daily_photo_deadline.strftime("%H:%M")} بوده است.'})

    morning=CampCommanderCheck.objects.filter(site=site,date=today,period='morning').first()
    if morning:
        raw=str((morning.answers or {}).get('workers_needed','')).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹','0123456789'))
        import re as _re
        match=_re.search(r'\d+',raw)
        if match:
            planned=int(match.group())
            if planned and summary['present_workers'] > planned:
                alerts.append({'level':'warning','title':'تعداد کارگر بیشتر از برنامه است','text':f"امروز {summary['present_workers']} نفر حاضرند؛ برنامه صبح {planned} نفر بوده است."})

    for p in CampProject.objects.filter(site=site,status='active'):
        if p.over_budget:
            alerts.append({'level':'danger','title':f'پروژه {p.name} از بودجه عبور کرده','text':f'هزینه واقعی {toman(p.actual_cost)} در برابر برآورد {toman(p.estimated_cost)} تومان.'})
        if p.last_progress_date and (today-p.last_progress_date).days>=4:
            alerts.append({'level':'warning','title':f'پروژه {p.name} بدون پیشرفت','text':f'{(today-p.last_progress_date).days} روز از آخرین ثبت پیشرفت گذشته است.'})
    return alerts[:20]


@camp_required()
def camp_dashboard(request):
    if request.camp_role=='worker':
        return redirect('camp_tasks')
    site=request.camp_site
    summary=_today_summary(site)
    today=timezone.localdate()
    alerts=_camp_alerts(site)
    active_qs=CampProject.objects.filter(site=site,status='active')
    delayed_qs=active_qs.filter(last_progress_date__lt=today-timedelta(days=3)).order_by('last_progress_date')
    low_items=[x for x in CampInventoryItem.objects.filter(site=site,is_active=True) if x.stock_status!='ok']
    # Seven-day cost trend for the executive dashboard. Values are pre-normalized for CSS bars.
    trend=[]
    raw=[]
    for n in range(6,-1,-1):
        d=today-timedelta(days=n)
        worker=CampWorkerAttendance.objects.filter(worker__site=site,date=d,is_present=True).aggregate(x=Sum('wage_for_day'))['x'] or 0
        food=CampFoodPlan.objects.filter(site=site,date=d).aggregate(x=Sum('actual_cost'))['x'] or 0
        purchase=CampInvoice.objects.filter(purchase__site=site,created_at__date=d).aggregate(x=Sum('final_amount'))['x'] or 0
        raw.append((d,worker+food+purchase))
    max_cost=max([Decimal(x[1]) for x in raw] or [Decimal('1')]) or Decimal('1')
    avg_cost=(sum((Decimal(x[1]) for x in raw),Decimal('0'))/Decimal(len(raw))) if raw else Decimal('0')
    for d,value in raw:
        pct=max(10,int((Decimal(value)/max_cost)*100)) if value else 8
        trend.append({'date':d,'value':value,'pct':pct})
    paid_invoices=CampInvoice.objects.filter(purchase__site=site).select_related('purchase').order_by('-created_at')
    context={
        'site':site,'summary':summary,'alerts':alerts,
        'active_projects':active_qs.count(),
        'pending_purchases':CampPurchaseRequest.objects.filter(site=site,status='pending').count(),
        'urgent_purchases':CampPurchaseRequest.objects.filter(site=site,status='pending',urgency='urgent').count(),
        'low_inventory':len(low_items),
        'low_items':low_items[:4],
        'delayed_projects':delayed_qs.count(),
        'delayed_project_list':delayed_qs[:4],
        'recent_invoices':paid_invoices[:4],
        'invoice_today_count':CampInvoice.objects.filter(purchase__site=site,created_at__date=today).count(),
        'expense_trend':trend,
        'expense_average':avg_cost,
        'expense_max':max_cost,
        'expense_min':min([Decimal(x[1]) for x in raw] or [Decimal('0')]),
        'alert_count':len(alerts),
        'role':request.camp_role,
    }
    return render(request,'core/camp/dashboard.html',context)


@camp_required(['owner','supervisor','finance'])
def purchase_list(request):
    qs=CampPurchaseRequest.objects.filter(site=request.camp_site).select_related('requester','approved_by')
    return render(request,'core/camp/purchases.html',{'purchases':qs,'role':request.camp_role,'site':request.camp_site})


@camp_required(['owner','supervisor'])
def purchase_create(request):
    form=CampPurchaseRequestForm(request.POST or None,request.FILES or None)
    if request.method=='POST' and form.is_valid():
        x=form.save(commit=False); x.site=request.camp_site; x.requester=request.user; x.save()
        messages.success(request,'درخواست خرید ثبت شد و منتظر تأیید است.')
        return redirect('camp_purchase_list')
    return render(request,'core/camp/form.html',{'form':form,'title':'درخواست خرید جدید','button':'ثبت درخواست','back':'/camp/purchases/'})


@camp_required(['owner','supervisor'])
def purchase_review(request,pk,action):
    x=get_object_or_404(CampPurchaseRequest,pk=pk,site=request.camp_site)
    if request.method!='POST': return redirect('camp_purchase_list')
    if action=='reject':
        x.status='rejected'; x.rejection_note=(request.POST.get('note') or '')[:250]
    elif action=='approve':
        if x.requires_owner_approval and request.camp_role!='owner':
            messages.warning(request,'این خرید بالاتر از سقف مجاز است و تأیید Owner لازم دارد.')
            return redirect('camp_purchase_list')
        x.status='approved'; x.approved_by=request.user; x.approved_at=timezone.now()
        if request.camp_role=='owner':
            x.owner_approved_by=request.user; x.owner_approved_at=timezone.now()
    x.save()
    messages.success(request,'وضعیت خرید به‌روزرسانی شد.')
    return redirect('camp_purchase_list')


@camp_required(['owner','supervisor','finance'])
def invoice_create(request,pk):
    purchase=get_object_or_404(CampPurchaseRequest,pk=pk,site=request.camp_site)
    instance=getattr(purchase,'invoice',None)
    form=CampInvoiceForm(request.POST or None,request.FILES or None,instance=instance)
    if request.method=='POST' and form.is_valid():
        x=form.save(commit=False); x.purchase=purchase; x.created_by=request.user
        if x.is_paid and not x.paid_at: x.paid_at=timezone.now()
        x.save()
        purchase.status='paid' if x.is_paid else 'purchased'; purchase.save(update_fields=['status','updated_at'])
        messages.success(request,'فاکتور خرید ثبت شد.')
        return redirect('camp_purchase_list')
    return render(request,'core/camp/form.html',{'form':form,'title':f'فاکتور: {purchase.item_name}','button':'ذخیره فاکتور','back':'/camp/purchases/'})


@camp_required(['owner','supervisor','finance'])
def inventory(request):
    items=CampInventoryItem.objects.filter(site=request.camp_site,is_active=True)
    return render(request,'core/camp/inventory.html',{'items':items,'role':request.camp_role})


@camp_required(['owner','supervisor'])
def inventory_item_create(request):
    form=CampInventoryItemForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        x=form.save(commit=False); x.site=request.camp_site; x.save()
        return redirect('camp_inventory')
    return render(request,'core/camp/form.html',{'form':form,'title':'کالای جدید انبار','button':'ذخیره','back':'/camp/inventory/'})


@camp_required(['owner','supervisor'])
@transaction.atomic
def inventory_movement(request,pk):
    item=get_object_or_404(CampInventoryItem,pk=pk,site=request.camp_site)
    form=CampInventoryMovementForm(request.POST or None)
    form.fields['reference_purchase'].queryset=CampPurchaseRequest.objects.filter(site=request.camp_site)
    if request.method=='POST' and form.is_valid():
        x=form.save(commit=False); x.item=item; x.created_by=request.user
        qty=x.quantity
        new_stock=item.current_stock+qty if x.movement_type=='in' else item.current_stock-qty
        if new_stock < 0:
            form.add_error('quantity','موجودی برای این خروج کافی نیست.')
        else:
            x.save(); item.current_stock=new_stock
            if x.movement_type=='in': item.last_purchase_date=x.date
            item.save()
            messages.success(request,'گردش انبار ثبت شد.')
            return redirect('camp_inventory')
    return render(request,'core/camp/form.html',{'form':form,'title':f'ورود/خروج انبار: {item.name}','button':'ثبت گردش','back':'/camp/inventory/'})


@camp_required(['owner','supervisor'])
def workers(request):
    qs=CampWorker.objects.filter(site=request.camp_site)
    today=timezone.localdate()
    attendance={x.worker_id:x for x in CampWorkerAttendance.objects.filter(worker__site=request.camp_site,date=today)}
    rows=[(w,attendance.get(w.id)) for w in qs]
    return render(request,'core/camp/workers.html',{'rows':rows,'today':today})


@camp_required(['owner','supervisor'])
def worker_create(request):
    form=CampWorkerForm(request.POST or None,request.FILES or None)
    if request.method=='POST' and form.is_valid():
        x=form.save(commit=False); x.site=request.camp_site; x.save(); return redirect('camp_workers')
    return render(request,'core/camp/form.html',{'form':form,'title':'کارگر / نیروی جدید','button':'ذخیره','back':'/camp/workers/'})


@camp_required(['owner','supervisor'])
def worker_attendance(request):
    form=CampWorkerAttendanceForm(request.POST or None)
    form.fields['worker'].queryset=CampWorker.objects.filter(site=request.camp_site,status__in=['active','temporary'])
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        obj,_=CampWorkerAttendance.objects.update_or_create(worker=d['worker'],date=d['date'],defaults={
            'is_present':d['is_present'],'start_time':d['start_time'],'end_time':d['end_time'],
            'work_done':d['work_done'],'wage_for_day':d['wage_for_day'] or d['worker'].daily_wage,
            'notes':d['notes'],'created_by':request.user})
        return redirect('camp_workers')
    return render(request,'core/camp/form.html',{'form':form,'title':'ثبت حضور و دستمزد','button':'ثبت','back':'/camp/workers/'})


@camp_required()
def tasks(request):
    date=timezone.localdate()
    try:
        if request.GET.get('date'): date=parse_jalali(request.GET['date'])
    except Exception: pass
    qs=CampDailyTask.objects.filter(site=request.camp_site,date=date).select_related('project')
    if request.camp_role=='worker':
        name=request.user.get_full_name() or request.user.username
        qs=qs.filter(responsible__icontains=name)
    return render(request,'core/camp/tasks.html',{'tasks':qs,'date':date,'role':request.camp_role})


@camp_required(['owner','supervisor'])
def task_create(request):
    form=CampDailyTaskForm(request.POST or None,request.FILES or None)
    form.fields['project'].queryset=CampProject.objects.filter(site=request.camp_site)
    if request.method=='POST' and form.is_valid():
        x=form.save(commit=False); x.site=request.camp_site; x.created_by=request.user; x.save(); return redirect('camp_tasks')
    return render(request,'core/camp/form.html',{'form':form,'title':'وظیفه روزانه جدید','button':'ثبت وظیفه','back':'/camp/tasks/'})


@camp_required(['owner','supervisor','worker'])
def task_toggle(request,pk,status):
    x=get_object_or_404(CampDailyTask,pk=pk,site=request.camp_site)
    if status in dict(CampDailyTask.STATUS) and request.method=='POST':
        x.status=status; x.save(update_fields=['status'])
    return redirect('camp_tasks')


@camp_required(['owner','supervisor','finance'])
def projects(request):
    qs=CampProject.objects.filter(site=request.camp_site)
    return render(request,'core/camp/projects.html',{'projects':qs,'role':request.camp_role})


@camp_required(['owner','supervisor'])
def project_create(request):
    form=CampProjectForm(request.POST or None,request.FILES or None)
    if request.method=='POST' and form.is_valid():
        x=form.save(commit=False); x.site=request.camp_site
        if x.progress and not x.last_progress_date: x.last_progress_date=timezone.localdate()
        x.save(); return redirect('camp_projects')
    return render(request,'core/camp/form.html',{'form':form,'title':'پروژه کمپ','button':'ذخیره پروژه','back':'/camp/projects/'})


@camp_required(['owner','supervisor','finance'])
def food_plan(request):
    qs=CampFoodPlan.objects.filter(site=request.camp_site).order_by('-date')[:21]
    week_start=timezone.localdate()-timedelta(days=6)
    week_cost=CampFoodPlan.objects.filter(site=request.camp_site,date__gte=week_start).aggregate(x=Sum('actual_cost'))['x'] or 0
    return render(request,'core/camp/food.html',{'plans':qs,'week_cost':week_cost,'role':request.camp_role})


@camp_required(['owner','supervisor'])
def food_create(request):
    form=CampFoodPlanForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        x=form.save(commit=False); x.site=request.camp_site; x.save(); return redirect('camp_food')
    return render(request,'core/camp/form.html',{'form':form,'title':'برنامه غذایی','button':'ذخیره','back':'/camp/food/'})


@camp_required()
def photos(request):
    qs=CampDailyPhoto.objects.filter(site=request.camp_site).select_related('uploader','project')[:80]
    return render(request,'core/camp/photos.html',{'photos':qs,'role':request.camp_role})


@camp_required(['owner','supervisor','worker'])
def photo_create(request):
    form=CampDailyPhotoForm(request.POST or None,request.FILES or None)
    form.fields['project'].queryset=CampProject.objects.filter(site=request.camp_site)
    if request.method=='POST' and form.is_valid():
        x=form.save(commit=False); x.site=request.camp_site; x.uploader=request.user; x.save(); return redirect('camp_photos')
    return render(request,'core/camp/form.html',{'form':form,'title':'ثبت عکس روزانه','button':'آپلود عکس','back':'/camp/photos/'})


@camp_required(['owner','supervisor','finance'])
def reports(request):
    site=request.camp_site; today=timezone.localdate()
    summary=_today_summary(site)
    month_start=today.replace(day=1)
    month_purchase=CampInvoice.objects.filter(purchase__site=site,created_at__date__range=(month_start,today)).aggregate(x=Sum('final_amount'))['x'] or 0
    month_worker=CampWorkerAttendance.objects.filter(worker__site=site,date__gte=month_start,is_present=True).aggregate(x=Sum('wage_for_day'))['x'] or 0
    month_food=CampFoodPlan.objects.filter(site=site,date__gte=month_start).aggregate(x=Sum('actual_cost'))['x'] or 0
    data={
        **summary,'month_cost':month_purchase+month_worker+month_food,
        'month_food':month_food,'month_worker':month_worker,
        'material_cost':CampInvoice.objects.filter(purchase__site=site,purchase__category='material',created_at__date__range=(month_start,today)).aggregate(x=Sum('final_amount'))['x'] or 0,
        'purchases_done':CampPurchaseRequest.objects.filter(site=site,status__in=['purchased','paid'],request_date=today).count(),
        'without_invoice':CampPurchaseRequest.objects.filter(site=site,status__in=['purchased','paid'],invoice__isnull=True).count(),
        'active_projects':CampProject.objects.filter(site=site,status='active').count(),
        'low_inventory':sum(1 for x in CampInventoryItem.objects.filter(site=site,is_active=True) if x.stock_status!='ok'),
    }
    return render(request,'core/camp/reports.html',{'data':data,'alerts':_camp_alerts(site)})




def _commander_daily_summary(site, day=None):
    day=day or timezone.localdate()
    summary=_today_summary(site)
    tasks=CampDailyTask.objects.filter(site=site,date=day)
    purchases=CampPurchaseRequest.objects.filter(site=site,request_date=day,status__in=['purchased','paid'])
    missing_invoices=purchases.filter(invoice__isnull=True).count()
    night=CampCommanderCheck.objects.filter(site=site,date=day,period='night').first()
    return {
        'date':day,
        'workers':summary['present_workers'],
        'tasks_done':tasks.filter(status='done').count(),
        'tasks_total':tasks.count(),
        'purchases':purchases.count(),
        'missing_invoices':missing_invoices,
        'cost':summary['today_cost'],
        'photos':summary['photos'],
        'issues':((night.answers or {}).get('issues','') if night else ''),
        'tomorrow':((night.answers or {}).get('tomorrow','') if night else ''),
    }

@camp_required(['owner'])
def commander(request):
    site=request.camp_site; today=timezone.localdate()
    checks={x.period:x for x in CampCommanderCheck.objects.filter(site=site,date=today)}
    morning_fields=[
        ('workers_needed','امروز چند نفر کارگر لازم است؟'),('main_work','کار اصلی امروز چیست؟'),
        ('urgent_purchase','خرید ضروری امروز چیست؟'),('food_stock','موجودی غذا کافی است؟'),
        ('urgent_project','آیا پروژه خاصی فوریت دارد؟'),('photo_owner','چه کسی مسئول ارسال عکس امروز است؟'),
        ('do_not_do','چه کاری نباید انجام شود؟')]
    night_fields=[
        ('done','امروز چه کارهایی انجام شد؟'),('not_done','چه کارهایی انجام نشد؟'),('spent','چقدر هزینه شد؟'),
        ('purchases','چه خریدهایی انجام شد؟'),('invoices','آیا فاکتورها آپلود شدند؟'),('photos','آیا عکس‌های روزانه ثبت شدند؟'),
        ('issues','مشکل یا حاشیه‌ای وجود داشت؟'),('tomorrow','برنامه فردا چیست؟')]
    if request.method=='POST':
        period=request.POST.get('period')
        fields=morning_fields if period=='morning' else night_fields
        answers={key:(request.POST.get(key) or '').strip() for key,_ in fields}
        CampCommanderCheck.objects.update_or_create(site=site,date=today,period=period,defaults={'answers':answers,'created_by':request.user})
        messages.success(request,'چک مدیریتی ذخیره شد.')
        return redirect('camp_commander')
    return render(request,'core/camp/commander.html',{
        'summary':_today_summary(site),'alerts':_camp_alerts(site),'checks':checks,
        'morning_fields':morning_fields,'night_fields':night_fields,'today':today,
        'daily_summary':_commander_daily_summary(site,today)})


@camp_required()
def camp_api_summary(request):
    data=_today_summary(request.camp_site)
    data={k:(str(v) if isinstance(v,Decimal) else v) for k,v in data.items()}
    data['date']=format_jalali(data.pop('today'))
    data['alerts']=_camp_alerts(request.camp_site)
    return JsonResponse(data,json_dumps_params={'ensure_ascii':False})


@camp_required(['owner'])
def seed_demo(request):
    if request.method=='POST':
        from .camp_seed import seed_camp_demo
        seed_camp_demo(request.user)
        messages.success(request,'داده نمونه Camp بارگذاری/به‌روزرسانی شد.')
    return redirect('camp_dashboard')
