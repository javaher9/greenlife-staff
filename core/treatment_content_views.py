"""Admin-owned diet/recommendation content library and doctor read-only preview."""
from pathlib import Path
from zipfile import BadZipFile

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from .models import (
    TreatmentCatalogItem, TreatmentRichContent, TreatmentRichSection, TreatmentRichMedia, TreatmentDietDayAudio,
)
from .treatment_content_service import import_five_sample_zip
from .treatment_content_layout import build_section_preview
from .diet_week_plan import DAYS as ORANGE_DAYS, SLOTS as ORANGE_SLOTS, LABELS as ORANGE_LABELS, build_orange_week, parse_legacy

_ALLOWED_IMAGE_EXT={'.jpg','.jpeg','.png','.webp','.gif'}
_ALLOWED_AUDIO_EXT={'.mp3','.m4a','.mp4','.wav','.ogg'}


def _role(request):
    return getattr(getattr(request.user,'profile',None),'role',None)


def _admin(request):
    return bool(
        request.user.is_superuser
        or (request.user.username or '').lower() in settings.EXECUTIVE_USERNAMES
        or _role(request)=='admin'
    )


def _admin_only(request):
    if not _admin(request):
        raise PermissionDenied('مدیریت محتوای رژیم و توصیه فقط برای ادمین فعال است.')


def _content_for_preview(request, item_id):
    if not _admin(request) and _role(request)!='doctor':
        raise PermissionDenied('فقط پزشک و ادمین می‌توانند این محتوا را ببینند.')
    content=get_object_or_404(
        TreatmentRichContent.objects.select_related('master_item'),master_item_id=item_id,
    )
    if not _admin(request) and (not content.is_active or not content.master_item.is_active):
        raise Http404('این محتوا در حال حاضر غیرفعال است.')
    return content


@login_required
@require_GET
def treatment_content_browse(request):
    if not _admin(request) and _role(request)!='doctor':
        raise PermissionDenied('فهرست محتوای پزشکی فقط برای پزشک یا ادمین است.')
    rows=TreatmentRichContent.objects.filter(
        is_active=True,master_item__is_active=True,
    ).select_related('master_item').order_by('master_item__category','master_item__name')
    return render(request,'core/treatment_content_browse.html',{'rows':rows})


@login_required
@require_GET
def treatment_content_preview(request, item_id):
    content=_content_for_preview(request,item_id)
    sections=[
        build_section_preview(section)
        for section in content.sections.prefetch_related('media').all()
    ]
    response=render(request,'core/treatment_content_preview.html',{
        'content':content,'sections':sections,'can_manage':_admin(request),
    })
    response['Cache-Control']='private, no-store'
    return response


@login_required
@require_http_methods(['GET','POST'])
def treatment_content_library(request):
    _admin_only(request)
    if request.method=='POST':
        uploaded=request.FILES.get('archive')
        if not uploaded:
            messages.error(request,'فایل ZIP خروجی پنج نمونه را انتخاب کنید.')
        elif uploaded.size>18_000_000 or not uploaded.name.lower().endswith('.zip'):
            messages.error(request,'فایل باید ZIP و کمتر از ۱۸ مگابایت باشد.')
        else:
            try:
                result=import_five_sample_zip(
                    uploaded.read(),
                    replace_existing=request.POST.get('replace_existing')=='1',
                )
            except Exception as exc:
                if isinstance(exc,(ValueError,ValidationError,BadZipFile)):
                    detail=str(exc)
                else:
                    detail='خطای پردازش فایل؛ هیچ موردی به‌عنوان واردشده تأیید نمی‌شود.'
                messages.error(request,detail)
            else:
                messages.success(
                    request,
                    f"ورود پنج نمونه: {result['created']} جدید، {result['updated']} جایگزین، "
                    f"{result['unchanged']} بدون تغییر؛ {result['files_saved']} تصویر از MHTML ذخیره شد.",
                )
                for warning in result['warnings']:
                    messages.warning(request,warning)
        return redirect('treatment_content_library')

    titles=['Keto-Fast','Sib-150','Por-150','R-250','نکات طلائی در لاغری']
    catalog=list(
        TreatmentCatalogItem.objects.filter(
            category__in=('diet','recommendation'),name__in=titles,branch__isnull=True,
        ).select_related('rich_content').order_by('category','name','id')
    )
    by_key={(item.category,item.name):item for item in catalog}
    rows=[{'title':name,'category':('recommendation' if name=='نکات طلائی در لاغری' else 'diet'),
           'item':by_key.get(('recommendation' if name=='نکات طلائی در لاغری' else 'diet',name))}
          for name in titles]
    return render(request,'core/treatment_content_library.html',{'rows':rows})


@login_required
@require_http_methods(['GET','POST'])
def treatment_content_manage(request, item_id):
    _admin_only(request)
    content=get_object_or_404(
        TreatmentRichContent.objects.select_related('master_item'),master_item_id=item_id,
    )
    if request.method=='POST':
        action=(request.POST.get('action') or '').strip()
        try:
            if action=='toggle':
                content.is_active=not content.is_active
                content.save(update_fields=['is_active','updated_at'])
                content.master_item.is_active=content.is_active
                content.master_item.save(update_fields=['is_active','updated_at'])
                messages.success(request,'وضعیت محتوا و قابلیت انتخاب آن در پنل پزشک هم‌زمان ذخیره شد.')
            elif action=='update_content':
                content.intro_warning=request.POST.get('intro_warning','')[:8000]
                content.display_title=(request.POST.get('display_title') or '').strip()[:160]
                content.hero_subtitle=(request.POST.get('hero_subtitle') or '').strip()[:240]
                content.slogan=(request.POST.get('slogan') or '').strip()[:240]
                content.slogan_external_url=(request.POST.get('slogan_external_url') or '').strip()[:1300]
                content.cover_external_url=request.POST.get('cover_external_url','')[:1300]
                content.audio_external_url=request.POST.get('audio_external_url','')[:1300]
                content.full_clean()
                content.save()
                messages.success(request,'اطلاعات عمومی ذخیره شد.')
            elif action=='save_section':
                section=get_object_or_404(content.sections,pk=request.POST.get('section_id'))
                section.title=(request.POST.get('title') or '').strip()[:200]
                section.day_number=max(0 if content.master_item.name=='Por-150' else 1,min(366,int(request.POST.get('day_number') or 1)))
                slot=(request.POST.get('meal_slot') or 'other').strip()
                if slot not in dict(TreatmentRichSection.MEAL_CHOICES):
                    raise ValueError('نوع وعده معتبر نیست.')
                section.meal_slot=slot
                raw_cal=(request.POST.get('estimated_kcal') or '').strip()
                section.estimated_kcal=max(0,min(9999,int(raw_cal))) if raw_cal else None
                section.body=request.POST.get('body','')[:150000]
                section.sort_order=max(0,min(9999,int(request.POST.get('sort_order','0'))))
                if not section.title:
                    raise ValueError('عنوان بخش نباید خالی باشد.')
                section.save()
                messages.success(request,'متن و ترتیب بخش ذخیره شد.')
            elif action=='add_section':
                title=(request.POST.get('title') or '').strip()[:200]
                if not title:
                    raise ValueError('عنوان بخش الزامی است.')
                max_order=(content.sections.order_by('-sort_order').values_list('sort_order',flat=True).first() or 0)
                day=max(0 if content.master_item.name=='Por-150' else 1,min(366,int(request.POST.get('day_number') or 1)))
                slot=(request.POST.get('meal_slot') or 'other').strip()
                if slot not in dict(TreatmentRichSection.MEAL_CHOICES):
                    raise ValueError('نوع وعده معتبر نیست.')
                content.sections.create(
                    title=title,body='',day_number=day,meal_slot=slot,
                    sort_order=min(max_order+10,9999),
                )
                messages.success(request,'بخش جدید افزوده شد.')
            elif action in ('save_orange_meal','clear_orange_meal'):
                # Isolated admin workflow for the Por-150 prototype only.
                if content.master_item.name!='Por-150' or content.master_item.category!='diet':
                    raise PermissionDenied('ویرایش هفت‌روزه فقط برای رژیم پرتقال فعال است.')
                day=int(request.POST.get('week_day','-1'))
                slot=(request.POST.get('week_slot') or '').strip()
                if day not in range(8) or slot not in (
                    'fasting','breakfast','snack_am','lunch','snack_pm','dinner',
                ):
                    raise ValueError('روز یا وعده نامعتبر است.')
                existing=content.sections.filter(day_number=day,meal_slot=slot)
                if action=='clear_orange_meal':
                    existing.delete()
                    messages.success(request,'تنظیم اختصاصی این وعده حذف شد؛ مقدار پیش‌فرض نشان داده می‌شود.')
                else:
                    body=(request.POST.get('week_body') or '').strip()[:150000]
                    kcal_raw=(request.POST.get('week_kcal') or '').strip()
                    kcal=int(kcal_raw) if kcal_raw else None
                    if kcal is not None and not 0<=kcal<=9999:
                        raise ValueError('کالری باید بین صفر و ۹۹۹۹ باشد.')
                    if not body:
                        raise ValueError('برای حذف تنظیم اختصاصی از دکمه بازگشت به پیش‌فرض استفاده کنید.')
                    primary=existing.order_by('id').first()
                    if primary is None:
                        order=(content.sections.order_by('-sort_order').values_list('sort_order',flat=True).first() or 0)
                        primary=content.sections.create(
                            title=ORANGE_LABELS[slot],day_number=day,meal_slot=slot,
                            sort_order=min(order+10,9999),body=body,estimated_kcal=kcal,
                        )
                    else:
                        primary.body=body
                        primary.estimated_kcal=kcal
                        primary.save(update_fields=['body','estimated_kcal'])
                    # Optional day-specific image; never touches imported MHTML media.
                    photo=request.FILES.get('week_image')
                    if photo:
                        if photo.size>5_000_000 or Path(photo.name).suffix.lower() not in _ALLOWED_IMAGE_EXT:
                            raise ValueError('عکس وعده باید تصویر معتبر و کمتر از ۵ مگابایت باشد.')
                        from PIL import Image
                        try:
                            im=Image.open(photo)
                            im.verify()
                            photo.seek(0)
                        except Exception as exc:
                            raise ValueError('فایل عکس معتبر نیست.') from exc
                        previous=primary.media.filter(kind='image').order_by('sort_order','id').first()
                        if previous is not None:
                            previous.uploaded_file.save(photo.name,photo,save=True)
                            previous.original_url=''
                            previous.sort_order=0
                            previous.inline_before_line=0
                            previous.is_responsive_duplicate=False
                            previous.save()
                        else:
                            picture=TreatmentRichMedia(
                                section=primary,kind='image',sort_order=0,inline_before_line=0,
                            )
                            picture.uploaded_file.save(photo.name,photo,save=True)
                    messages.success(request,'وعده انتخاب‌شده ذخیره شد؛ متن اصلی فایل تغییر نکرد.')
                return redirect(reverse('treatment_content_manage',args=[item_id])+f'?week_day={day}#orange-week-editor')
            elif action=='upload':
                kind=request.POST.get('kind','')
                file=request.FILES.get('media_file')
                if not file or file.size>12_000_000:
                    raise ValueError('فایل الزامی و حداکثر ۱۲ مگابایت است.')
                ext=Path(file.name).suffix.lower()
                allowed=_ALLOWED_IMAGE_EXT if kind=='image' else _ALLOWED_AUDIO_EXT
                if kind not in ('image','audio') or ext not in allowed:
                    raise ValueError('نوع فایل تصویر یا صوت معتبر نیست.')
                if kind=='image':
                    from PIL import Image
                    try:
                        im=Image.open(file)
                        im.verify()
                        file.seek(0)
                    except Exception:
                        raise ValueError('تصویر معتبر نیست.')
                location=request.POST.get('location','section')
                if location=='cover' and kind=='image':
                    content.cover_file.save(file.name,file,save=True)
                elif location=='audio' and kind=='audio':
                    content.audio_file.save(file.name,file,save=True)
                elif location=='slogan' and kind=='image':
                    content.slogan_image.save(file.name,file,save=True)
                elif location=='daily_audio' and kind=='audio':
                    day=max(1,min(366,int(request.POST.get('day_number') or 1)))
                    audio_row,_=TreatmentDietDayAudio.objects.get_or_create(
                        content=content,day_number=day,
                    )
                    audio_row.audio_file.save(file.name,file,save=True)
                else:
                    section=get_object_or_404(content.sections,pk=request.POST.get('section_id'))
                    position=(section.media.order_by('-sort_order').values_list('sort_order',flat=True).first() or 0)+10
                    media=TreatmentRichMedia(section=section,kind=kind,sort_order=min(position,9999))
                    media.uploaded_file.save(file.name,file,save=True)
                messages.success(request,'فایل روی سرور ذخیره شد.')
            elif action=='remove_day_audio':
                day=max(1,min(366,int(request.POST.get('day_number') or 1)))
                audio_row=get_object_or_404(TreatmentDietDayAudio,content=content,day_number=day)
                if audio_row.audio_file:
                    audio_row.audio_file.delete(save=False)
                audio_row.delete()
                messages.success(request,'صدای اختصاصی روز حذف شد.')
            elif action=='remove_media':
                medium=get_object_or_404(TreatmentRichMedia,pk=request.POST.get('media_id'),section__content=content)
                if medium.uploaded_file:
                    medium.uploaded_file.delete(save=False)
                medium.delete()
                messages.success(request,'رسانه حذف شد.')
            else:
                raise ValueError('عملیات مشخص نیست.')
        except (ValueError,ValidationError) as exc:
            messages.error(request,str(exc))
        return redirect('treatment_content_manage',item_id=item_id)
    sections=list(content.sections.prefetch_related('media').all())
    orange_only=(content.master_item.category=='diet' and content.master_item.name=='Por-150')
    orange_rows=[]
    orange_day=1
    if orange_only:
        try:
            orange_day=int(request.GET.get('week_day','1'))
        except (ValueError,TypeError):
            orange_day=1
        if orange_day not in range(8):
            orange_day=1
        week=build_orange_week(sections)
        common={}
        for section in sections:
            if section.title.strip()=='برنامه غذایی':
                shared,_=parse_legacy(section)
                for slot,cards in shared.items(): common[slot]=cards
        for slot in ('fasting','breakfast','snack_am','lunch','snack_pm','dinner'):
            choices=([card for card in week[orange_day] if card['slot']==slot]
                     if orange_day else [
                         card for card in common.get(slot,[])
                     ])
            manual=[section for section in sections
                    if section.meal_slot==slot and section.day_number==orange_day]
            if orange_day==0 and manual:
                choices=[{'body':section.body,'calories':section.estimated_kcal}
                         for section in manual]
            orange_rows.append({
                'slot':slot,'name':ORANGE_LABELS[slot],
                'body':'\n\n'.join(card['body'] for card in choices if card['body']),
                'kcal':manual[0].estimated_kcal if manual else (
                    choices[0]['calories'] if len(choices)==1 else None
                ),
                'manual':bool(manual),
            })
    return render(request,'core/treatment_content_manage.html',{
        'content':content,'sections':sections,'day_audios':list(content.daily_audio.all()),
        'orange_only':orange_only,'orange_day':orange_day,
        'orange_days':list(enumerate(ORANGE_DAYS,start=1)),'orange_rows':orange_rows,
    })
