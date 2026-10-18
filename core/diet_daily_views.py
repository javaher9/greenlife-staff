"""Mobile-first, read-only presentation of actual stored diets.

Clinical source text/media is never generated or rewritten by this view.
Only staff with doctor/admin permission may preview the diet until a
patient-scoped authorization flow is available.
"""
import re

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.templatetags.static import static
from .diet_week_plan import DAYS, build_orange_week
from django.views.decorators.http import require_GET

from .treatment_content_layout import build_section_preview
from .treatment_content_views import _content_for_preview, _admin

SLOT_LABELS={
    'breakfast':'صبحانه','snack_am':'میان‌وعده صبح','lunch':'ناهار',
    'snack_pm':'عصرانه','dinner':'شام','other':'توضیحات',
}
SLOT_SYMBOLS={'breakfast':'☀','snack_am':'☘','lunch':'☀','snack_pm':'☕','dinner':'☾','other':'✦'}


def _detected_slot(title, body):
    sample=(title+' '+body[:55]).replace('‌',' ')
    if 'صبحانه' in sample:
        return 'breakfast'
    if 'ناهار' in sample:
        return 'lunch'
    if 'عصرانه' in sample:
        return 'snack_pm'
    if 'شام' in sample:
        return 'dinner'
    if 'میان وعده' in sample or 'میان‌وعده' in sample:
        return 'snack_am'
    return 'other'


def _prepare_cards(sections):
    cards=[]
    for section in sections:
        section=build_section_preview(section)
        if section.meal_slot!='other':
            images=[
                media for media in section.media.all()
                if media.kind=='image' and media.url and not media.is_responsive_duplicate
            ]
            body=section.body.strip()
            cards.append({
                'slot':section.meal_slot,'label':SLOT_LABELS[section.meal_slot],
                'icon':SLOT_SYMBOLS[section.meal_slot],
                'title':section.title,
                'summary':body.splitlines()[:3],'body':body,
                'photo':images[0].url if images else '',
                'calories':section.estimated_kcal,
                'audio':section.audio_media[0].url if section.audio_media else '',
            })
            continue
        # Legacy MHTML remains in its original order. Each interleaved text/photo
        # group is displayed together; unrelated paragraphs stay text-only.
        used=False
        for row in section.preview_rows:
            body=(row['text'] or '').strip()
            images=row['images']
            if not body and not images:
                continue
            slot=_detected_slot(section.title,body)
            cards.append({
                'slot':slot,'label':SLOT_LABELS[slot] if slot!='other' else section.title,
                'icon':SLOT_SYMBOLS[slot],'title':section.title,
                'summary':body.splitlines()[:3],'body':body,
                'photo':images[0].url if images else '',
                'calories':None,'audio':'',
            })
            used=True
        for media in section.footer_images:
            cards.append({
                'slot':'other','label':section.title,'icon':'✦','title':section.title,
                'summary':[],'body':'','photo':media.url,'calories':None,'audio':'',
            })
        if not used and not section.footer_images and section.body:
            cards.append({
                'slot':'other','label':section.title,'icon':'✦','title':section.title,
                'summary':section.body.splitlines()[:3],'body':section.body,
                'photo':'','calories':None,'audio':'',
            })
    return cards



# Curated food photography for missing Por-150 meal pictures only.
# Never replace an image already attached by the diet editor.
ORANGE_FOOD_PHOTOS = {
    'orange': 'https://images.unsplash.com/photo-1547514701-42782101795e?w=640&fit=crop&auto=format&q=85',
    'salad': 'https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=640&fit=crop&auto=format&q=85',
    'tea': 'https://images.unsplash.com/photo-1544787219-7f47ccb76574?w=640&fit=crop&auto=format&q=85',
    'nuts': 'https://images.unsplash.com/photo-1599599810769-bcde5a160d32?w=640&fit=crop&auto=format&q=85',
    'egg': 'https://images.unsplash.com/photo-1506976785307-8732e854ad03?w=640&fit=crop&auto=format&q=85',
    'tuna': 'https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=640&fit=crop&auto=format&q=85',
    'water': 'https://images.unsplash.com/photo-1437482078695-73f5ca6c96e2?w=640&fit=crop&auto=format&q=85',
    'fruit': 'https://images.unsplash.com/photo-1490474418585-ba9bad8fd0ea?w=640&fit=crop&auto=format&q=85',
    'vegetables': 'https://images.unsplash.com/photo-1540420773420-3366772f4999?w=640&fit=crop&auto=format&q=85',
    'carrots': 'https://images.unsplash.com/photo-1447175008436-054170c2e979?w=640&fit=crop&auto=format&q=85',
}
ORANGE_SLOGAN_FALLBACK = 'https://images.unsplash.com/photo-1743926465923-cfd31487cb88?w=1100&fit=crop&auto=format&q=80'

def _orange_food_photo(card):
    if card.get('photo'):
        return card['photo']
    body = (card.get('body') or '').replace('‌', ' ')
    slot = card.get('slot')
    if slot == 'other':
        return ORANGE_FOOD_PHOTOS['water'] if ('آب' in body or 'مایعات' in body) else ORANGE_FOOD_PHOTOS['vegetables']
    if 'هویج' in body:
        return ORANGE_FOOD_PHOTOS['carrots']
    if 'تن ماهی' in body:
        return ORANGE_FOOD_PHOTOS['tuna']
    if 'تخم مرغ' in body:
        return ORANGE_FOOD_PHOTOS['egg']
    if 'سالاد' in body or 'سبزی' in body:
        return ORANGE_FOOD_PHOTOS['salad']
    if 'چای' in body or 'دمنوش' in body or 'قهوه' in body:
        return ORANGE_FOOD_PHOTOS['tea']
    if 'آجیل' in body or 'گردو' in body or 'بادام' in body:
        return ORANGE_FOOD_PHOTOS['nuts']
    if 'پرتقال' in body or 'آب پرتقال' in body:
        return ORANGE_FOOD_PHOTOS['orange']
    if 'میوه' in body:
        return ORANGE_FOOD_PHOTOS['fruit']
    if slot in ('breakfast','snack_am','snack_pm'):
        return ORANGE_FOOD_PHOTOS['fruit']
    return ORANGE_FOOD_PHOTOS['vegetables']


@login_required
@require_GET
def diet_daily_preview(request,item_id):
    content=_content_for_preview(request,item_id)
    if content.master_item.category!='diet':
        raise Http404('این مورد رژیم غذایی نیست.')
    sections=list(content.sections.prefetch_related('media').all())
    orange_only=(content.master_item.name=='Por-150')
    audio_by_day={row.day_number:row for row in content.daily_audio.all()}
    if orange_only:
        # Saturday=1 ... Friday=7, calculated in the configured local timezone.
        available_days=list(range(1,8))
        suggested_day=(timezone.localdate().weekday()+2)%7+1
        week=build_orange_week(sections)
    else:
        # Every non-orange diet preserves its previous behavior.
        available_days=sorted({s.day_number for s in sections}|set(audio_by_day)) or [1]
        suggested_day=available_days[0]
        week=None
    try:
        chosen=int(request.GET.get('day',suggested_day))
    except (ValueError,TypeError):
        chosen=suggested_day
    if chosen not in available_days:
        raise Http404('برای این روز برنامه ثبت نشده است.')
    i=available_days.index(chosen)
    prev_day=available_days[i-1] if i>0 else None
    next_day=available_days[i+1] if i<len(available_days)-1 else None
    day_audio=audio_by_day.get(chosen)
    audio_url=day_audio.url if day_audio and day_audio.url else content.audio_url
    # The legacy catalog identifier should never leak as the patient-facing
    # headline. Respect any custom title chosen by the editor.
    saved_title=(content.display_title or '').strip()
    title=('رژیم پرتقال' if orange_only and saved_title in ('','Por-150')
           else saved_title or content.master_item.name)
    slogan=content.slogan or ('لاغری یعنی زندگی بهتر' if content.master_item.name=='Por-150' else '')
    slogan_photo=content.slogan_image.url if content.slogan_image else content.slogan_external_url
    cards = week[chosen] if orange_only else _prepare_cards(s for s in sections if s.day_number==chosen)
    if orange_only:
        cards = [dict(card, summary=(card.get('body') or '').splitlines(), photo=_orange_food_photo(card),
                      fallback_food='carrots' if 'هویج' in (card.get('body') or '') else 'fruit')
                 for card in cards]
    if orange_only and not slogan_photo:
        slogan_photo = static('core/diet/orange-slogan-woman.webp')
    response=render(request,'core/diet_daily.html',{
        'content':content,'title':title,'subtitle':content.hero_subtitle or 'برنامه غذایی اختصاصی',
        'slogan':slogan,'slogan_photo':slogan_photo,'day':chosen,
        'days':available_days,'day_total':max(available_days),'prev_day':prev_day,'next_day':next_day,
        'cards':cards,
        'orange_only':orange_only,'day_name':DAYS[chosen-1] if orange_only else '',
        'day_choices':list(enumerate(DAYS,start=1)) if orange_only else [],
        'audio_url':audio_url,'can_manage':_admin(request),
    })
    response['Cache-Control']='private, no-store'
    return response
