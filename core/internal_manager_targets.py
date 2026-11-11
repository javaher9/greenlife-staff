"""Qualitative projection of the existing monthly sales engine.

Only allowlisted strings cross this boundary. Numeric plans, receipts and
performance values stay local and are never added to template/API context.
"""
from datetime import datetime, time
from types import SimpleNamespace
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from .supervision_text import safe_label
from .country_workspace import scoped_queryset
from .models import Branch, EmployeeProfile, FinancialTransaction
from .sales_target_models import SalesTargetBand, TargetPercentPolicy
from .sales_target_views import _month_params, _money, _gauge_row, ZERO
from .call_center_identity import call_center_display_name
from django.utils import timezone

LABELS = {
    'heavy': ('پایین‌تر از حد قابل قبول', 'علت وضعیت و اقدام اصلاحی پیگیری شود'),
    'light': ('پایین‌تر از کف فروش', 'برنامه رسیدن به کف فروش پیگیری شود'),
    'neutral': ('رسیدن به کف فروش', 'روند حفظ شود'),
    'one': ('رسیدن به تارگت اول', 'روند حفظ شود'),
    'two': ('رسیدن به تارگت دوم', 'روند حفظ شود'),
    'unset': ('هدف تعریف نشده', 'تعریف هدف توسط مدیر مجاز لازم است'),
    'unknown': ('داده کافی نیست', 'منبع دریافت‌های تأییدشده بررسی شود'),
}


def target_statuses(request):
    jy, jm, start_date, end_date, today = _month_params(request)
    period = f'{jy}-{jm:02d}'
    policy = TargetPercentPolicy.objects.filter(period_year=jy,period_month=jm).first() or TargetPercentPolicy()
    plans = {}
    for stored in SalesTargetBand.objects.filter(period_year=jy,period_month=jm):
        heavy,floor,one,two = policy.bands(stored.sales_floor)
        plans[stored.key.removeprefix(period+':')] = SimpleNamespace(heavy_limit=heavy,sales_floor=floor,target_one=one,target_two=two)
    branches = scoped_queryset(request, Branch.objects.filter(is_active=True)).filter(
        Q(country__code='IR') | Q(country__isnull=True)
    ).exclude(name__icontains='ارومیه').exclude(name__icontains='افسریه').order_by('name')
    flowers = scoped_queryset(request, EmployeeProfile.objects.filter(
        is_active=True,user__is_active=True,role='call_center'
    )).select_related('user').order_by('user__first_name','pk')
    income = FinancialTransaction.objects.filter(source='manual',entry_type='inc',review_status='approved',
        occurred_at__gte=timezone.make_aware(datetime.combine(start_date,time.min)),
        occurred_at__lt=timezone.make_aware(datetime.combine(end_date,time.min)))
    by_branch = {r['branch_id']:r['amount'] for r in income.values('branch_id').annotate(amount=Sum('amount'))}
    by_flower = {r['owner']:r['amount'] for r in income.annotate(owner=Coalesce('call_center_owner_id','appointment__lead__first_appointment_by_id')).values('owner').annotate(amount=Sum('amount'))}
    def row(key,name,amount):
        level = _gauge_row(key,name,_money(amount),plans)['level']
        if key in plans and amount is None:
            level = 'unknown'
        label,action = LABELS[level]
        return {'name':safe_label(name),'level':level,'status':label,'action':action}
    return {'period_label':f'{jy}/{jm:02d}', 'period_year':jy,'period_month':jm,
        'target_branches':[row(f'branch:{b.pk}',b.name,by_branch.get(b.pk)) for b in branches],
        'target_flowers':[row(f'flower:{p.user_id}',call_center_display_name(p),by_flower.get(p.user_id)) for p in flowers]}
