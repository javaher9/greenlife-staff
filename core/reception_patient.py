from .models import PatientProfile, lead_phone_variants, normalize_lead_phone


def ensure_reception_patient(appointment, user):
    return ensure_patient_for_contact(
        appointment.full_name, appointment.phone, user, branch=appointment.branch,
    )


def ensure_patient_for_contact(full_name, phone, user, *, branch=None):
    """Resolve the patient account without overwriting existing clinical history."""
    phone = normalize_lead_phone(phone)
    if not phone:
        return None
    existing = PatientProfile.objects.filter(
        phone__in=lead_phone_variants(phone)
    ).order_by('id').first()
    if existing:
        return existing
    patient, _ = PatientProfile.objects.get_or_create(
        phone=phone,
        defaults={'full_name': full_name, 'home_branch': branch, 'created_by': user},
    )
    return patient
