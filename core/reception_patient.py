from .models import PatientProfile, lead_phone_variants, normalize_lead_phone


def ensure_reception_patient(appointment, user):
    """Resolve reception identity without overwriting existing clinical history."""
    phone = normalize_lead_phone(appointment.phone)
    if not phone:
        return None
    existing = PatientProfile.objects.filter(
        phone__in=lead_phone_variants(phone)
    ).order_by('id').first()
    if existing:
        return existing
    patient, _ = PatientProfile.objects.get_or_create(
        phone=phone,
        defaults={'full_name': appointment.full_name,
                  'home_branch': appointment.branch, 'created_by': user},
    )
    return patient
