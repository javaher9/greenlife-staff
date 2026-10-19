"""Two isolated read-only Excel diet previews; never touch clinical database.

Temporary approval surface for IDs 45 and 44 only, preserving all Excel day
texts and existing media. Not an importer or a patient-facing prescription.
"""
import json
import re
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .diet_meal_icons import meal_illustration_url
from .diet_week_plan import DAYS
from .treatment_content_views import _admin

_SAMPLE_FILES={45:'diet_excel_sample_saf.json',44:'diet_excel_sample_dam.json'}
_SLOT_LABELS={
    'صبحانه':('breakfast','صبحانه'),
    'میانوعدهصبح':('snack_am','میان‌وعده صبح'),
    'میانصبح':('snack_am','میان‌وعده صبح'),
    'ناهار':('lunch','ناهار'),
    'میانوعدهعصر':('snack_pm','عصرانه'),
    'عصرانه':('snack_pm','عصرانه'),
    'شام':('dinner','شام'),
    'میانوعدهشب':('bedtime','میان‌وعده شب'),
    'قبلازخواب':('bedtime','قبل از خواب'),
}

@lru_cache(maxsize=2)
def _source(legacy_id):
    filename=_SAMPLE_FILES.get(legacy_id)
    if not filename:
        raise Http404('این نمونه در حال بررسی نیست.')
    with (Path(__file__).parent/filename).open(encoding='utf-8') as file:
        data=json.load(file)
    if data.get('id')!=legacy_id or len(data.get('days',[]))!=7:
        raise ValueError('ساختار نمونه اکسل معتبر نیست.')
    return data

def preview_cards():
    return [
        {'id':source['id'],'name':source['code'],
         'cover_url':source.get('cover') or ''}
        for legacy_id in (45,44)
        for source in [_source(legacy_id)]
    ]

def parse_day_meals(source_text):
    """Label-only parsing: unchanged clinical portions and no fabricated snacks."""
    cards=[]
    for line in (source_text or '').splitlines():
        line=line.strip()
        if not line:
            continue
        match=re.match(r'^([^:：]+)[:：]\s*(.*)$',line)
        if not match:
            # Prevent silent data loss or unsafe guessing.
            raise ValueError('یک ردیف وعده در نمونه اکسل برچسب معتبر ندارد.')
        title=match.group(1).replace('\u200c',' ').replace(' ','').strip()
        info=_SLOT_LABELS.get(title)
        if not info:
            raise ValueError('نام وعده ناشناخته در نمونه اکسل: '+match.group(1))
        slot,label=info
        body=match.group(2).strip()
        if not body:
            continue
        cards.append({
            'slot':slot,'label':label,'title':label,'body':body,
            'summary':[body],'illustration_url':meal_illustration_url(slot),
            'photo':'','calories':None,
        })
    return cards

@login_required
@require_GET
def excel_diet_sample_preview(request,legacy_id):
    if not _admin(request):
        raise PermissionDenied('نمونه‌های اکسل فقط پیش‌نمایش مدیر هستند.')
    source=_source(legacy_id)
    try:
        day=int(request.GET.get('day','1'))
    except (TypeError,ValueError):
        raise Http404('روز نامعتبر است.')
    if day<1 or day>7:
        raise Http404('روز نامعتبر است.')
    cards=parse_day_meals(source['days'][day-1])
    response=render(request,'core/diet_daily.html',{
        'content':SimpleNamespace(cover_url=source.get('cover') or ''),
        'title':source['code'],
        'subtitle':'پیش‌نمایش آزمایشی اکسل · هنوز در بانک رژیم‌ها ذخیره نشده',
        'slogan':source.get('slogan') or '','slogan_photo':'',
        'day':day,'day_name':DAYS[day-1],
        'days':list(range(1,8)),'day_total':7,
        'prev_day':day-1 if day>1 else None,
        'next_day':day+1 if day<7 else None,
        'day_choices':list(enumerate(DAYS,start=1)),
        'cards':cards,'audio_url':'','orange_only':True,
        'can_manage':False,
    })
    response['Cache-Control']='private, no-store'
    return response
