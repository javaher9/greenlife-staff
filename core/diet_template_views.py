"""Staff-only preview of two intentionally separate diet presentation templates."""
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .diet_week_plan import DAYS, build_orange_week
from .diet_ramadan_plan import build_ramadan_week, SLOTS as RAMADAN_SLOTS
from .treatment_content_views import _admin, _content_for_preview

TYPES={'weekly':'برنامه غذایی هفت‌روزه','ramadan':'برنامه ماه رمضان'}


def _deduplicate(items):
    """Suppress repeated responsive text but preserve distinct food alternatives."""
    seen=set()
    out=[]
    for item in items:
        key=(item['slot'],(item.get('body') or '').strip(),item.get('photo') or '')
        if key not in seen:
            out.append(item)
            seen.add(key)
    return out


@login_required
@require_GET
def diet_template_preview(request,item_id):
    content=_content_for_preview(request,item_id)
    kind=content.presentation_template
    if content.master_item.category!='diet' or kind not in TYPES:
        raise Http404('برای این برنامه قالب هفت‌روزه یا رمضان انتخاب نشده است.')
    sections=list(content.sections.prefetch_related('media').all())
    if kind=='ramadan':
        raw_days=build_ramadan_week(sections)
        slot_order=RAMADAN_SLOTS
    else:
        raw_days=build_orange_week(sections)
        slot_order=None
    days=[]
    for i,label in enumerate(DAYS,start=1):
        cards=_deduplicate(raw_days.get(i,[]))
        # Exactly the source or admin-edited portions, without fabricated calories.
        days.append({'number':i,'label':label,'cards':cards})
    extras=[
        section for section in sections
        if section.meal_slot=='other' and section.title.strip()!='برنامه غذایی'
    ]
    audio={clip.day_number:clip.url for clip in content.daily_audio.all() if clip.url}
    response=render(request,'core/diet_two_templates.html',{
        'content':content,'title':content.display_title or content.master_item.name,
        'template_name':TYPES[kind],'kind':kind,'days':days,'extras':extras,
        'day_audio':audio,'can_manage':_admin(request),
    })
    response['Cache-Control']='private, no-store'
    return response
