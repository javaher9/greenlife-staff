from django.utils import timezone
from core.models import VisitAppointment


def gandom_operator():
    from core.models import EmployeeProfile
    from core.call_center_identity import call_center_display_name
    matches = [p for p in EmployeeProfile.objects.filter(is_active=True, user__is_active=True).select_related('user')
               if call_center_display_name(p) == 'گندم']
    return matches[0] if len(matches) == 1 else None


def ensure_school_lead(enrollment):
    """Called under the enrollment/program lock. Only parent contact enters CRM."""
    from django.conf import settings
    from django.contrib.auth.models import User
    from core.models import ReferralProfile, ReferralLead, CallCenterLeadGroup
    operator = gandom_operator()
    source, _ = User.objects.get_or_create(username='schools-lead-source', defaults={'is_active': False, 'password': '!', 'first_name': 'طرح مدارس'})
    referrer, _ = ReferralProfile.objects.get_or_create(user=source, defaults={'referral_code': 'SCHOOLS-SOURCE'})
    group, _ = CallCenterLeadGroup.objects.get_or_create(name='مدارس')
    p = enrollment.program
    description = f'مدرسه: {p.organization.name} | گروه / دوره: {p.title} | شعبه: {p.organization.branch.name} | پیگیری طرح مدارس توسط گندم؛ هماهنگی با خانم مرادی. شناسه ثبت‌نام: {enrollment.pk}'
    lead, created = ReferralLead.objects.get_or_create(school_enrollment=enrollment, defaults={
        'referrer': referrer, 'group': group, 'full_name': enrollment.parent_name,
        'phone': enrollment.member.phone, 'source': 'link',
        'interested_service': 'هماهنگی طرح مدارس', 'notes': description,
        'source_url': settings.PUBLIC_BASE_URL.rstrip('/') + '/schools/families/' + str(enrollment.pk) + '/',
        'assigned_to': operator, 'assigned_at': timezone.now() if operator else None,
    })
    if not created and not lead.assigned_to_id and operator:
        lead.assigned_to = operator
        lead.assigned_at = timezone.now()
        lead.save(update_fields=['assigned_to', 'assigned_at'])
    return lead


def sync_appointment(enrollment, user):
    """Book the adult's family visit; never merge children into phone-keyed patient records."""
    if enrollment.status not in ('booked', 'attended'):
        if enrollment.visit_appointment_id:
            appointment = enrollment.visit_appointment
            if appointment.status not in ('cancelled', 'no_show'):
                appointment.status = 'cancelled'
                appointment.save()
            if enrollment.status != 'cancelled':
                enrollment.visit_appointment = None
        return
    at = timezone.localtime(enrollment.appointment_at)
    appointment = enrollment.visit_appointment if enrollment.visit_appointment_id else VisitAppointment(created_by=user)
    appointment.branch = enrollment.program.organization.branch
    appointment.full_name = enrollment.parent_name
    appointment.phone = enrollment.member.phone
    appointment.service = 'طرح مدارس · مراجعه خانواده'
    appointment.appointment_date = at.date()
    appointment.appointment_time = at.time().replace(tzinfo=None)
    appointment.status = 'arrived' if enrollment.status == 'attended' else 'booked'
    appointment.source = 'admin'
    appointment.notes = f'طرح مدارس؛ والد همراه. پرونده فرزندان در بخش مدارس / پرونده رشد. شناسه خانواده: {enrollment.pk}'
    appointment.save()
    enrollment.visit_appointment = appointment
