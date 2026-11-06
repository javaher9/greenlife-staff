"""Public consultation form for visitors arriving from GreenLife's website."""
from urllib.parse import urlparse

from django.db import transaction
from django.shortcuts import render

from .instagram_views import InstagramLeadForm
from .lead_ingest_views import _assign_lead, _source_profile
from .models import DuplicateLeadError, LEAD_DUPLICATE_MESSAGE, ReferralLead


def _website_page(raw):
    """Accept attribution only from GreenLife's own public website."""
    value = str(raw or '').strip()[:500]
    try:
        parsed = urlparse(value)
    except ValueError:
        return ''
    if parsed.scheme not in ('http', 'https') or (parsed.hostname or '').lower() not in (
        'greenlifeclinics.com', 'www.greenlifeclinics.com',
    ):
        return ''
    return value


def website_lead(request):
    source_page = _website_page(request.GET.get('page'))
    cta_label = str(request.GET.get('cta') or '').strip()[:120]
    form = InstagramLeadForm(request.POST or None)
    completed = False

    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                lead = ReferralLead.objects.create(
                    referrer=_source_profile('website'),
                    full_name=data['full_name'].strip(),
                    phone=data['phone'],
                    interested_service=(data.get('interested_service') or '').strip(),
                    status='new',
                    source='link',
                    source_url=source_page,
                    notes='ورودی فرم مشاوره وب‌سایت' + (
                        ' | صفحه: ' + source_page if source_page else ''
                    ) + (' | دکمه: ' + cta_label if cta_label else ''),
                )
                _assign_lead(lead, 'website')
        except DuplicateLeadError:
            form.add_error('phone', LEAD_DUPLICATE_MESSAGE)
        else:
            completed = True
            form = InstagramLeadForm()

    return render(request, 'core/instagram_lead.html', {
        'form': form,
        'completed': completed,
        'website_form': True,
    })
