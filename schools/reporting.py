from datetime import timedelta
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from .models import FamilyEnrollment

METRICS = [('all', 'ثبت‌نام خانواده'), ('activated', 'فعال‌سازی گرین‌لایف من'), ('attended', 'مراجعه خانواده'), ('requested', 'درخواست مشاوره والد'), ('treatment', 'شروع درمان والد')]
TASKS = [('new', 'ثبت‌نام جدید'), ('pending', 'پذیرش تکمیل نشده'), ('ready', 'نوبت نگرفته'), ('today', 'نوبت امروز'), ('no_show', 'عدم حضور'), ('followup', 'موعد پیگیری')]

def criterion(key):
    now = timezone.now()
    return {
        'all': Q(), 'activated': Q(app_activated_at__isnull=False),
        'attended': Q(status='attended'), 'requested': Q(adult_opt_in=True),
        'treatment': Q(adult_opt_in=True, adult_outcome='treatment'),
        'new': Q(created_at__gte=now-timedelta(days=2), status__in=('pending', 'ready', 'waiting'), staff_note=''),
        'pending': Q(status='pending'),
        'ready': Q(status='ready'), 'today': Q(appointment_at__date=timezone.localdate(), status='booked'),
        'no_show': Q(visit_appointment__status='no_show') | Q(status='booked', appointment_at__lt=now),
        'followup': Q(next_follow_up_at__lte=now) & ~Q(status='cancelled'),
    }.get(key, Q())

def select(request, programs):
    query = request.GET.get('q', '').strip()[:160]
    if query:
        programs = programs.filter(Q(organization__name__icontains=query) | Q(title__icontains=query))
    for key, field in [('school', 'pk'), ('branch', 'organization__branch_id'), ('coordinator', 'coordinator_id')]:
        value = request.GET.get(key, '')
        if value.isascii() and value.isdecimal() and len(value) < 12:
            programs = programs.filter(**{field: int(value)})
    state = request.GET.get('state', '')
    if state:
        programs = programs.filter(state=state)
    families = FamilyEnrollment.objects.filter(program__in=programs)
    for key, lookup in [('from', 'created_at__date__gte'), ('to', 'created_at__date__lte')]:
        try:
            value = parse_date(request.GET.get(key, ''))
        except ValueError:
            value = None
        if value:
            families = families.filter(**{lookup: value})
    return programs, families

def metric_cards(request, families, keys=METRICS):
    data = families.aggregate(**{key: Count('pk', filter=criterion(key)) for key, label in keys})
    total = families.count()
    cards = []
    for key, label in keys:
        params = request.GET.copy()
        params.pop('page', None)
        params['bucket'] = key
        cards.append({'key': key, 'label': label, 'count': data[key], 'percent': round(data[key]*100/total) if total else 0, 'query': params.urlencode()})
    return cards

def financials(families, programs):
    sold = families.filter(adult_opt_in=True, adult_outcome='treatment')
    result = sold.aggregate(contracts=Sum('contract_amount'), priced=Count('contract_amount'), buyers=Count('pk'))
    costs = programs.aggregate(cost=Sum('recorded_cost'), costed=Count('recorded_cost'), programs=Count('pk'))
    result.update(costs)
    result['average'] = round(result['contracts']/result['priced']) if result['priced'] else None
    result['estimate'] = result['contracts']-costs['cost'] if result['priced'] and result['priced']==result['buyers'] and costs['programs'] and costs['costed']==costs['programs'] else None
    return result
