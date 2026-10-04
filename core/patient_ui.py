from .models import PatientProfile, lead_phone_variants, normalize_lead_phone


def attach_patient_photos(items, phone_attr='phone'):
    """Attach transient patient_photo_url/patient_initial to appointment-like objects."""
    items=list(items)
    canonicals=[]
    variants=set()
    for item in items:
        phone=getattr(item,phone_attr,'')
        canonical=normalize_lead_phone(phone)
        canonicals.append(canonical)
        variants.update(lead_phone_variants(canonical))
    photo_map={}
    if variants:
        for patient in PatientProfile.objects.filter(phone__in=variants).exclude(photo='').only('phone','photo','full_name'):
            canonical=normalize_lead_phone(patient.phone)
            if not canonical or not patient.photo:
                continue
            try:
                url=patient.photo.url
            except Exception:
                url=''
            if url and canonical not in photo_map:
                photo_map[canonical]=url
    for item,canonical in zip(items,canonicals):
        setattr(item,'patient_photo_url',photo_map.get(canonical,''))
        name=(getattr(item,'full_name','') or '').strip()
        setattr(item,'patient_initial',name[:1] if name else '•')
    return items


def patient_photo_url_for_phone(phone):
    canonical=normalize_lead_phone(phone)
    if not canonical:
        return ''
    patient=(
        PatientProfile.objects.filter(phone__in=lead_phone_variants(canonical))
        .exclude(photo='')
        .only('photo')
        .order_by('id')
        .first()
    )
    if not patient or not patient.photo:
        return ''
    try:
        return patient.photo.url
    except Exception:
        return ''
