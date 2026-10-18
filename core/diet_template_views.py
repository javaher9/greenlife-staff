"""Staff-only preview of two intentionally separate diet presentation templates."""
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .diet_week_plan import DAYS, build_orange_week
from .diet_ramadan_plan import build_ramadan_week, SLOTS as RAMADAN_SLOTS
from .diet_thirteen_plan import build_thirteen_days
from .treatment_content_layout import build_section_preview
from .diet_extras_display import prepare_diet_extras
from .treatment_content_views import _admin, _content_for_preview

TYPES={'weekly':'برنامه غذایی هفت‌روزه','ramadan':'برنامه ماه رمضان',
       'thirteen':'برنامه سیزده‌روزه','text':'برنامه غذایی متنی'}


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
    # Por-150 is the one approved mobile pilot. Do not route it through
    # the unrelated generic weekly template; other diets stay unchanged.
    if (content.master_item.category=='diet' and
            content.master_item.name=='Por-150' and kind=='weekly'):
        from .diet_daily_views import diet_daily_preview
        return diet_daily_preview(request,item_id)
    if content.master_item.category!='diet' or kind not in TYPES:
        raise Http404('برای این برنامه قالب هفت‌روزه یا رمضان انتخاب نشده است.')
    sections=list(content.sections.prefetch_related('media').all())
    title=content.display_title or content.master_item.name
    if kind=='text':
        pages=[build_section_preview(section) for section in sections if section.meal_slot=='other']
        # Existing CRM paragraphs and their attached photos are never discarded.
        response=render(request,'core/diet_text_pages.html',{
            'content':content,'title':title,'pages':pages,'can_manage':_admin(request),
        })
        response['Cache-Control']='private, no-store'
        return response
    unmapped=[]
    if kind=='thirteen':
        raw_days,unmapped=build_thirteen_days(sections)
        names=[f'روز {n}' for n in range(1,14)]
    elif kind=='ramadan':
        raw_days=build_ramadan_week(sections)
        names=list(DAYS)
    else:
        raw_days=build_orange_week(sections)
        names=list(DAYS)
    days=[
        {'number':i,'label':label,'cards':_deduplicate(raw_days.get(i,[]))}
        for i,label in enumerate(names,start=1)
    ]
    extras=prepare_diet_extras(
        sections,
        quota_text=content.quota_text,
        free_foods_text=content.free_foods_text,
        notes_text=content.diet_notes_text,
    )
    response=render(request,'core/diet_two_templates.html',{
        'content':content,'title':title,'template_name':TYPES[kind],
        'kind':kind,'days':days,'extras':extras,'unmapped':unmapped,
        'can_manage':_admin(request),
    })
    response['Cache-Control']='private, no-store'
    return response
