"""Recent lead paths for the executive map, joined only through CRM relations."""
from django.db.models import Max, OuterRef, Subquery

from .call_center_identity import FLOWER_NAME_RULES, call_center_display_name
from .lead_group_names import normalized_group_name
from .models import ReferralLead, VisitAppointment


FLOWER_NAMES = {name for _, name in FLOWER_NAME_RULES}


def _origin(lead):
    if lead.school_enrollment_id:
        return 'مدارس'
    machine_sources = {
        'lead-source-website': 'وب‌سایت', 'lead-source-instagram': 'اینستاگرام',
        'lead-source-telegram': 'تلگرام', 'lead-source-bale': 'بله',
        'lead-source-whatsapp': 'واتساپ', 'lead-source-partner': 'همکار',
        'lead-source-campaign': 'کمپین', 'lead-source-crm': 'CRM',
    }
    recorded = machine_sources.get(lead.referrer.user.username)
    if recorded:
        return recorded
    group = normalized_group_name(lead.group.name) if lead.group_id else ''
    return {'وب سایت': 'وب‌سایت'}.get(group, group) or 'منبع ثبت نشده'


def recent_lead_journeys(start, now, limit=12):
    # Bound each candidate stream separately so a booking today can surface
    # an older lead, even when today's intake is busy.
    leads = ReferralLead.objects
    ids = set()
    for timestamp in ('created_at', 'assigned_at'):
        ids.update(leads.filter(**{timestamp + '__range': (start, now)})
                   .order_by('-' + timestamp, '-pk').values_list('pk', flat=True)[:limit])
    # Group before limiting: several bookings for one lead use a single slot.
    ids.update(VisitAppointment.objects.filter(lead__isnull=False, created_at__range=(start, now))
               .values('lead_id').annotate(latest=Max('created_at')).order_by('-latest', '-lead_id')
               .values_list('lead_id', flat=True)[:limit])
    appointments = VisitAppointment.objects.filter(lead_id=OuterRef('pk'), created_at__lte=now)
    active = appointments.exclude(status='cancelled').order_by('-created_at', '-pk')
    latest = appointments.order_by('-created_at', '-pk')
    records = leads.filter(pk__in=ids, created_at__lte=now).select_related(
        'referrer__user', 'assigned_to__user', 'group',
    ).only(
        'pk', 'created_at', 'assigned_at', 'school_enrollment_id', 'group__name',
        'referrer__user__username', 'assigned_to__role', 'assigned_to__user__username',
        'assigned_to__user__first_name', 'assigned_to__user__last_name',
    ).annotate(
        booking_at=Subquery(active.values('created_at')[:1]),
        last_booking_at=Subquery(latest.values('created_at')[:1]),
    )
    result = []
    for lead in records:
        owner = lead.assigned_to
        assigned = lead.assigned_at if owner and lead.assigned_at and lead.assigned_at <= now else None
        booked = lead.booking_at
        last = max(filter(None, (lead.created_at, assigned, lead.last_booking_at)))
        owner_label = ''
        if owner:
            owner_label = 'مسئول پیگیری'
            if owner.role == 'call_center':
                alias = call_center_display_name(owner.user)
                owner_label = alias if alias in FLOWER_NAMES else 'گل بدون نام مستعار'
        result.append({
            'id': lead.pk, 'source': _origin(lead),
            'owner': owner_label,
            'created': lead.created_at.isoformat(), 'assigned': assigned.isoformat() if assigned else None,
            'booked': booked.isoformat() if booked else None,
            'cancelled': bool(lead.last_booking_at and not booked),
            'updated': last.isoformat(),
        })
    return sorted(result, key=lambda item: (item['updated'], item['id']), reverse=True)[:limit]
