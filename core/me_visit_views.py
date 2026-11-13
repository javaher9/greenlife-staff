"""Member-only visit tracking. Internal staff notes and follow-up times stay private."""
from datetime import datetime
from django.utils import timezone
from django.views.decorators.http import require_GET
from .customer_portal_views import _member
from .me_sync_views import reply


def visit_data(row):
    booking = row.visit_appointment
    appointment = None
    state = row.status
    if row.status == 'booked' and booking:
        state = booking.status
        at = timezone.make_aware(datetime.combine(booking.appointment_date, booking.appointment_time))
        if state == 'booked' and at < timezone.now():
            state = 'past'
        appointment = {
            'date': booking.appointment_date.isoformat(),
            'time': booking.appointment_time.strftime('%H:%M'),
            'status': booking.status, 'status_label': booking.get_status_display(),
        }
    elif row.status == 'booked':
        state = 'needs_review'
    messages = {
        'pending': ('درخواستت رسید', 'در انتظار بررسی', 'کالسنتر درخواستت را بررسی می‌کند. برای هماهنگی، منتظر تماس مرکز باش؛ هنوز نوبت قطعی نداری.', 1),
        'contacted': ('در حال هماهنگی هستیم', 'در حال پیگیری', 'پرونده‌ات در حال پیگیری است. زمان نهایی پس از تأیید مرکز همین‌جا نمایش داده می‌شود.', 2),
        'booked': ('قرار دیدارمان مشخص شد', 'نوبت تأییدشده', 'در روز و ساعت زیر به شعبهٔ انتخاب‌شده مراجعه کن. اگر نیاز به تغییر زمان داری، با مرکز هماهنگ کن.', 3),
        'arrived': ('خوش آمدی', 'حضور ثبت شد', 'حضورت در مرکز ثبت شده؛ برای ادامهٔ مراجعه با پذیرش همراه باش.', 4),
        'completed': ('مراجعه‌ات انجام شد', 'مراجعه تکمیل شد', 'این مراجعه تکمیل شده است. برای ادامهٔ خدمات، راهنمایی تیم مرکز را دنبال کن.', 4),
        'cancelled': ('نوبت لغو شده است', 'نوبت لغو شد', 'این زمان دیگر فعال نیست. برای انتخاب زمان تازه با مرکز تماس بگیر.', 0),
        'no_show': ('برای یک قرار تازه هماهنگ کنیم', 'عدم مراجعه ثبت شده', 'برای این نوبت عدم مراجعه ثبت شده است. اگر اشتباهی رخ داده یا زمان تازه می‌خواهی، با مرکز تماس بگیر.', 0),
        'past': ('وضعیت مراجعه را بررسی کنیم', 'زمان نوبت گذشته', 'زمان ثبت‌شده گذشته است و نتیجهٔ مراجعه هنوز تکمیل نشده. برای بررسی یا هماهنگی دوباره با مرکز تماس بگیر.', 0),
        'declined': ('این درخواست بسته شده', 'بسته‌شده', 'پیگیری این درخواست پایان یافته و نوبت فعالی برای آن وجود ندارد. برای هماهنگی تازه می‌توانی درخواست جدید بدهی یا با مرکز تماس بگیری.', 0),
        'needs_review': ('نیاز به بررسی مرکز', 'در حال بررسی نوبت', 'اطلاعات نوبت قطعی در دسترس نیست. پیش از مراجعه با مرکز هماهنگ کن.', 0),
    }
    title, label, next_step, stage = messages.get(state, messages['needs_review'])
    return {
        'id': row.pk, 'state': state, 'title': title, 'label': label,
        'next_step': next_step, 'stage': stage, 'branch': row.branch.name,
        'created_at': row.created_at.isoformat(),
        'preferred_date': row.preferred_date.isoformat() if row.preferred_date else None,
        'preferred_time': row.get_daypart_display(), 'appointment': appointment,
    }


@require_GET
def visits(request):
    member = _member(request)
    if not member:
        return reply({'authenticated': False}, 401)
    rows = member.requests.filter(kind='visit').select_related('branch', 'visit_appointment')
    data = [visit_data(row) for row in rows.order_by('-created_at', '-pk')[:20]]
    # Open coordination and upcoming/ongoing visits remain above closed history.
    priority = {'booked': 0, 'arrived': 1, 'contacted': 2, 'pending': 3}
    data.sort(key=lambda item: priority.get(item['state'], 4))
    return reply({'authenticated': True, 'requests': data, 'checked_at': timezone.now().isoformat()})
