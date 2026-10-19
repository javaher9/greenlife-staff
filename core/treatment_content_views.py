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
from .treatment_crm_diet_transfer import import_one_crm_diet
from .treatment_content_layout import build_section_preview
from .treatment_content_edit_rows import inline_edit_rows,replace_one_line
from .diet_week_plan import DAYS as ORANGE_DAYS, SLOTS as ORANGE_SLOTS, LABELS as ORANGE_LABELS, build_orange_week, parse_legacy
from .diet_ramadan_plan import SLOTS as RAMADAN_SLOTS, LABELS as RAMADAN_LABELS, build_ramadan_week
from .diet_thirteen_plan import build_thirteen_days

_ALLOWED_IMAGE_EXT={'.jpg','.jpeg','.png','.webp','.gif'}


def _validate_meal_photo(photo):
    if not photo or photo.size>5_000_000 or Path(photo.name).suffix.lower() not in _ALLOWED_IMAGE_EXT:
        raise ValueError('عکس باید JPG، PNG، WebP یا GIF و کمتر از ۵ مگابایت باشد.')
    from PIL import Image
    try:
        image=Image.open(photo)
        image.verify()
        photo.seek(0)
    except Exception as exc:
        raise ValueError('فایل تصویری معتبر نیست.') from exc


def _valid_line_anchor(section,raw):
    try:
        line=int(raw)
    except (TypeError,ValueError) as exc:
        raise ValueError('ردیف تصویر معتبر نیست.') from exc
    if not 0<=line<=len(section.body.splitlines()):
        raise ValueError('شماره ردیف در این بخش وجود ندارد.')
    return line

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
    from .diet_excel_sample_previews import preview_cards
    return render(request,'core/treatment_content_browse.html',{
        'rows':rows,'excel_preview_cards':preview_cards() if _admin(request) else [],
    })


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
    # Full 34-weekly-diet XLSX import is admin-only and two-step by design.
    # Previewing never saves medical records. A repeated confirmation is safe.
    import base64
    from .treatment_excel_weekly_import import extract_workbook, validate_batch, import_weekly_diets
    action=(request.POST.get('action') or '') if request.method=='POST' else ''
    if action=='all_excel_preview':
        from .treatment_excel_all_import import read_all_diets
        weights=request.FILES.get('all_weight_excel')
        ramadan=request.FILES.get('all_ramadan_excel')
        if not weights or not ramadan or not all(
            f.name.lower().endswith('.xlsx') and f.size<=300_000
            for f in (weights,ramadan)
        ):
            messages.error(request,'هر دو فایل XLSX لاغری و رمضان، هر کدام حداکثر ۳۰۰ کیلوبایت، الزامی هستند.')
        else:
            try:
                wb=weights.read()
                rb=ramadan.read()
                weekly,other=read_all_diets(wb,rb)
                request.session['all_diets_pending']=[base64.b64encode(wb).decode('ascii'),base64.b64encode(rb).decode('ascii')]
                request.session.modified=True
                messages.success(request,f'هر ۴۶ رژیم شناسایی شد: {len(weekly)} هفت‌روزه و {len(other)} سایر قالب‌ها. هنوز چیزی ذخیره نشده است.')
            except ValueError as exc:
                messages.error(request,str(exc))
        return redirect('treatment_content_library')
    if action=='all_excel_import':
        from .treatment_excel_all_import import import_all_diets
        pending=request.session.get('all_diets_pending')
        if not pending or len(pending)!=2:
            messages.error(request,'ابتدا هر دو فایل اکسل را برای پیش‌نمایش بارگذاری کنید.')
        else:
            try:
                result=import_all_diets(base64.b64decode(pending[0]),base64.b64decode(pending[1]),request.user)
                request.session.pop('all_diets_pending',None)
                request.session.modified=True
                messages.success(request,
                    f"نتیجه انتقال ۴۶ رژیم: {result['filled']} تکمیل، "
                    f"{result['created']} رکورد جدید، {result['skipped']} رکورد قبلی بدون بازنویسی. "
                    "رژیم‌های جدید تا بازبینی پزشکی غیرفعال می‌مانند.")
            except (ValueError,ValidationError) as exc:
                messages.error(request,str(exc))
        return redirect('treatment_content_library')
    if action=='weekly_excel_preview':
        uploaded=request.FILES.get('weekly_excel')
        if not uploaded or not uploaded.name.lower().endswith('.xlsx'):
            messages.error(request,'فایل XLSX رژیم‌های لاغری را انتخاب کنید.')
        elif uploaded.size>300_000:
            messages.error(request,'حجم فایل بیشتر از حد مجاز ۳۰۰ کیلوبایت است.')
        else:
            try:
                raw=uploaded.read()
                entries=extract_workbook(raw)
                request.session['weekly_excel_pending']=base64.b64encode(raw).decode('ascii')
                request.session.modified=True
                messages.success(request,f'فایل بررسی شد؛ {len(entries)} رژیم هفت‌روزه آماده تأیید است.')
            except ValueError as exc:
                messages.error(request,str(exc))
        return redirect('treatment_content_library')
    if action=='weekly_excel_import':
        pending=request.session.get('weekly_excel_pending')
        if not pending:
            messages.error(request,'ابتدا فایل اکسل را بررسی کنید.')
        else:
            try:
                entries=extract_workbook(base64.b64decode(pending))
                result=import_weekly_diets(entries,request.user)
                request.session.pop('weekly_excel_pending',None)
                messages.success(request,
                    f"انتقال ایمن انجام شد: {result['created']} رژیم جدید، "
                    f"{result['filled']} رژیم با محتوای اکسل، "
                    f"{result['skipped']} رژیم دارای محتوای قبلی و بدون بازنویسی. "
                    "رژیم‌های تازه در حالت پیش‌نویس هستند.")
            except (ValueError,ValidationError) as exc:
                messages.error(request,str(exc))
        return redirect('treatment_content_library')
    if request.method=='POST' and request.POST.get('action')=='create_diet':
        title=(request.POST.get('diet_name') or '').strip()
        template=(request.POST.get('diet_template') or '').strip()
        if not title or len(title)>180:
            messages.error(request,'نام برنامه الزامی است و نباید بیش از ۱۸۰ حرف باشد.')
        elif template not in ('weekly','ramadan','thirteen','text'):
            messages.error(request,'ابتدا یکی از چهار قالب اصلی را انتخاب کنید.')
        else:
            from django.db import transaction
            with transaction.atomic():
                exists=TreatmentCatalogItem.objects.filter(
                    category='diet',name__iexact=title,branch__isnull=True,
                ).first()
                if exists:
                    messages.error(request,'برنامه‌ای با این نام از قبل در بانک اصلی ثبت شده است.')
                else:
                    item=TreatmentCatalogItem.objects.create(
                        name=title,category='diet',branch=None,
                        is_active=False,created_by=request.user,
                    )
                    TreatmentRichContent.objects.create(
                        master_item=item,presentation_template=template,is_active=False,
                        origin='ایجاد توسط مدیر؛ در انتظار تکمیل',
                    )
                    messages.success(request,'برنامه جدید به‌صورت پیش‌نویس ساخته شد. وعده‌ها و عکس‌ها را تکمیل و سپس فعال کنید.')
                    return redirect('treatment_content_manage',item_id=item.pk)
        return redirect('treatment_content_library')
    if request.method=='POST' and request.POST.get('action')=='start_edit':
        item=get_object_or_404(
            TreatmentCatalogItem,pk=request.POST.get('item_id'),
            branch__isnull=True,category__in=('diet','recommendation'),
        )
        TreatmentRichContent.objects.get_or_create(
            master_item=item,
            defaults={'is_active':False,'origin':'پنل مدیریت — در انتظار تکمیل محتوا'},
        )
        return redirect('treatment_content_manage',item_id=item.pk)
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

    catalog=list(
        TreatmentCatalogItem.objects.filter(
            category__in=('diet','recommendation'),branch__isnull=True,
        ).select_related('rich_content').order_by('category','sort_order','name','id')
    )
    rows=[{'title':item.name,'category':item.category,'item':item} for item in catalog]
    weekly_excel_preview=[]
    pending=request.session.get('weekly_excel_pending')
    if pending:
        try:
            weekly_excel_preview=validate_batch(extract_workbook(base64.b64decode(pending)))
        except ValueError as exc:
            request.session.pop('weekly_excel_pending',None)
            messages.error(request,'فایل در انتظار تأیید معتبر نیست: '+str(exc))
    count_diets=sum(row['category']=='diet' for row in rows)
    from .diet_excel_sample_previews import preview_cards
    return render(request,'core/treatment_content_library.html',{
        'rows':rows,'count_diets':count_diets,'weekly_excel_preview':weekly_excel_preview,
        'all_diets_ready':bool(request.session.get('all_diets_pending')),
        'excel_preview_cards':preview_cards(),
    })


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
            if action=='crm_import_diet':
                if content.master_item.category!='diet':
                    raise PermissionDenied('انتقال خودکار فقط برای برنامه غذایی فعال است.')
                result=import_one_crm_diet(content.master_item)
                messages.success(
                    request,
                    f"محتوای {result['sections']} بخش از CRM دریافت و در پیش‌نویس ثبت شد؛ "
                    f"{result['media_saved']} تصویر محلی ذخیره شد. تا زمان تأیید مدیر غیرفعال است.",
                )
                if result['missing']:
                    messages.warning(request,f"{result['missing']} تصویر در پاسخ CRM نشانی معتبر نداشت.")
            elif action=='toggle':
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
            elif action=='save_diet_template':
                if content.master_item.category!='diet':
                    raise ValueError('این تنظیمات فقط برای برنامه غذایی است.')
                template=(request.POST.get('presentation_template') or '').strip()
                if template not in ('legacy','weekly','ramadan','thirteen','text'):
                    raise ValueError('نوع قالب نامعتبر است.')
                content.presentation_template=template
                content.quota_text=request.POST.get('quota_text','')[:25000]
                content.free_foods_text=request.POST.get('free_foods_text','')[:25000]
                content.diet_notes_text=request.POST.get('diet_notes_text','')[:25000]
                content.save(update_fields=[
                    'presentation_template','quota_text','free_foods_text','diet_notes_text','updated_at',
                ])
                messages.success(request,'نوع قالب و اطلاعات سهمیه/غذاهای آزاد ذخیره شد.')
            elif action in ('save_template_meal','clear_template_meal','remove_template_photo'):
                if content.master_item.category!='diet' or content.presentation_template not in ('weekly','ramadan','thirteen'):
                    raise PermissionDenied('ویرایش روزانه فقط برای قالب هفتگی یا رمضان فعال است.')
                day=int(request.POST.get('template_day','-1'))
                slot=(request.POST.get('template_slot') or '').strip()
                allowed=(RAMADAN_SLOTS if content.presentation_template=='ramadan' else ORANGE_SLOTS)
                labels=(RAMADAN_LABELS if content.presentation_template=='ramadan' else ORANGE_LABELS)
                if day not in range(14 if content.presentation_template=='thirteen' else 8) or slot not in allowed or slot=='other':
                    raise ValueError('روز یا وعده انتخاب‌شده معتبر نیست.')
                existing=content.sections.filter(day_number=day,meal_slot=slot)
                if action=='clear_template_meal':
                    existing.delete()
                    messages.success(request,'تنظیم اختصاصی این وعده پاک شد؛ نسخه اصلی نمایش داده می‌شود.')
                else:
                    body=(request.POST.get('template_body') or '').strip()[:150000]
                    primary=existing.order_by('id').first()
                    if action=='save_template_meal' and not body:
                        raise ValueError('متن وعده نباید خالی باشد.')
                    if primary is None:
                        if not body:
                            raise ValueError('ابتدا برای این وعده متن تأییدشده ثبت کنید.')
                        order=content.sections.order_by('-sort_order').values_list('sort_order',flat=True).first() or 0
                        primary=content.sections.create(
                            title=labels[slot],body=body,day_number=day,meal_slot=slot,
                            sort_order=min(order+10,9999),
                        )
                    if action=='remove_template_photo':
                        primary.media.filter(kind='image').delete()
                        messages.success(request,'تصویر همین وعده حذف شد؛ متن محفوظ ماند.')
                    else:
                        photo=request.FILES.get('template_image')
                        if photo:
                            _validate_meal_photo(photo)
                        raw_kcal=(request.POST.get('template_kcal') or '').strip()
                        kcal=int(raw_kcal) if raw_kcal else None
                        if kcal is not None and not 0<=kcal<=9999:
                            raise ValueError('کالری باید بین صفر و ۹۹۹۹ باشد.')
                        primary.body=body
                        primary.estimated_kcal=kcal
                        primary.save(update_fields=['body','estimated_kcal'])
                        if photo:
                            medium=primary.media.filter(kind='image').order_by('sort_order','pk').first()
                            if medium is None:
                                medium=TreatmentRichMedia(section=primary,kind='image',sort_order=0,inline_before_line=0)
                            medium.uploaded_file.save(photo.name,photo,save=False)
                            medium.original_url=''
                            medium.inline_before_line=0
                            medium.is_responsive_duplicate=False
                            medium.save()
                        messages.success(request,'تنظیم این وعده ذخیره شد؛ فایل اصلی رژیم تغییر نکرد.')
                return redirect(reverse('treatment_content_manage',args=[item_id])+f'?template_day={day}#structured-template-editor')
            elif action=='add_text_page':
                if content.master_item.category!='diet' or content.presentation_template!='text':
                    raise PermissionDenied('افزودن صفحه فقط برای برنامه متنی مجاز است.')
                title=(request.POST.get('page_title') or '').strip()[:200]
                body=request.POST.get('page_body','')[:150000]
                if not title or not body.strip():
                    raise ValueError('عنوان و متن صفحه باید مشخص باشد.')
                photo=request.FILES.get('page_image')
                if photo:
                    _validate_meal_photo(photo)
                order=(content.sections.order_by('-sort_order').values_list('sort_order',flat=True).first() or 0)
                section=content.sections.create(
                    title=title,body=body,day_number=0,meal_slot='other',
                    sort_order=min(order+10,9999),is_editor_page=True,
                )
                if photo:
                    media=TreatmentRichMedia(section=section,kind='image',sort_order=10,inline_before_line=0)
                    media.uploaded_file.save(photo.name,photo,save=True)
                messages.success(request,'صفحه متنی همراه متن و عکس آن افزوده شد.')
            elif action=='save_text_page':
                if content.presentation_template!='text' or content.master_item.category!='diet':
                    raise PermissionDenied('ویرایش صفحه در قالب متنی مجاز است.')
                section=get_object_or_404(content.sections,pk=request.POST.get('section_id'),meal_slot='other')
                title=(request.POST.get('page_title') or '').strip()[:200]
                if not title:
                    raise ValueError('عنوان صفحه نمی‌تواند خالی باشد.')
                section.title=title
                section.body=request.POST.get('page_body','')[:150000]
                section.sort_order=max(0,min(9999,int(request.POST.get('page_order','100'))))
                section.save(update_fields=['title','body','sort_order'])
                messages.success(request,'صفحه متنی و ترتیب آن ذخیره شد.')
            elif action=='delete_text_page':
                if content.master_item.category!='diet' or content.presentation_template!='text':
                    raise PermissionDenied('حذف صفحه فقط در قالب متنی مجاز است.')
                section=get_object_or_404(content.sections,pk=request.POST.get('section_id'),is_editor_page=True)
                section.delete()
                messages.success(request,'صفحه انتخاب‌شده حذف شد؛ متن اصلی واردشده از CRM محفوظ است.')
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
            elif action=='save_meal_line':
                section=get_object_or_404(content.sections,pk=request.POST.get('section_id'))
                line=_valid_line_anchor(section,request.POST.get('line_number'))
                replace_one_line(
                    section,line,request.POST.get('line_signature',''),
                    request.POST.get('line_text',''),
                )
                messages.success(request,'متن همین ردیف ذخیره شد؛ سایر وعده‌ها تغییر نکردند.')
            elif action in ('add_meal_image','replace_meal_image','delete_meal_image'):
                if action=='add_meal_image':
                    section=get_object_or_404(content.sections,pk=request.POST.get('section_id'))
                    line=_valid_line_anchor(section,request.POST.get('line_number'))
                    photo=request.FILES.get('meal_image')
                    _validate_meal_photo(photo)
                    position=(section.media.order_by('-sort_order').values_list('sort_order',flat=True).first() or 0)+10
                    medium=TreatmentRichMedia(
                        section=section,kind='image',sort_order=min(position,9999),
                        inline_before_line=line,
                    )
                    medium.uploaded_file.save(photo.name,photo,save=True)
                    messages.success(request,'تصویر کنار همین وعده اضافه شد.')
                else:
                    medium=get_object_or_404(
                        TreatmentRichMedia,pk=request.POST.get('media_id'),
                        section__content=content,kind='image',
                    )
                    if action=='replace_meal_image':
                        photo=request.FILES.get('meal_image')
                        _validate_meal_photo(photo)
                        medium.uploaded_file.save(photo.name,photo,save=False)
                        medium.original_url=''
                        medium.is_responsive_duplicate=False
                        medium.save()
                        messages.success(request,'عکس همین وعده جایگزین شد.')
                    else:
                        # Keep physical file for rollback; remove only the association.
                        medium.delete()
                        messages.success(request,'تصویر این وعده حذف شد.')
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
            elif action in ('save_orange_meal','clear_orange_meal','remove_orange_meal_image'):
                # Por-150 only: manual day/meal overrides preserve the imported source.
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
                    if not body:
                        raise ValueError('متن وعده نباید خالی باشد.')
                    primary=existing.order_by('id').first()
                    photo=request.FILES.get('week_image') if action=='save_orange_meal' else None
                    if photo:
                        _validate_meal_photo(photo)
                    kcal=None
                    if action=='save_orange_meal':
                        kcal_raw=(request.POST.get('week_kcal') or '').strip()
                        kcal=int(kcal_raw) if kcal_raw else None
                        if kcal is not None and not 0<=kcal<=9999:
                            raise ValueError('کالری باید بین صفر و ۹۹۹۹ باشد.')
                    if primary is None:
                        order=(content.sections.order_by('-sort_order').values_list('sort_order',flat=True).first() or 0)
                        primary=content.sections.create(
                            title=ORANGE_LABELS[slot],day_number=day,meal_slot=slot,
                            sort_order=min(order+10,9999),body=body,estimated_kcal=kcal,
                        )
                    elif action=='save_orange_meal':
                        primary.body=body
                        primary.estimated_kcal=kcal
                        primary.save(update_fields=['body','estimated_kcal'])
                    if action=='remove_orange_meal_image':
                        # A blank photo in an override hides the legacy default.
                        for medium in primary.media.filter(kind='image'):
                            medium.delete()
                        messages.success(request,'عکس همین وعده حذف شد؛ متن و سایر وعده‌ها محفوظ‌اند.')
                    else:
                        if photo:
                            previous=primary.media.filter(kind='image').order_by('sort_order','id').first()
                            if previous is not None:
                                previous.uploaded_file.save(photo.name,photo,save=False)
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
    for section in sections:
        section.inline_rows,section.unplaced_images=inline_edit_rows(section)
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
                choices=[{'body':section.body,'calories':section.estimated_kcal,
                          'photo':next((medium.url for medium in section.media.all()
                                        if medium.kind=='image' and medium.url), '')}
                         for section in manual]
            orange_rows.append({
                'slot':slot,'name':ORANGE_LABELS[slot],
                'body':'\n\n'.join(card['body'] for card in choices if card['body']),
                'kcal':manual[0].estimated_kcal if manual else (
                    choices[0]['calories'] if len(choices)==1 else None
                ),
                'manual':bool(manual),
                'photo':next((card.get('photo','') for card in choices if card.get('photo')), ''),
            })
    template_rows=[]
    template_day=1
    template_days=[]
    selected_template=content.presentation_template
    if content.master_item.category=='diet' and selected_template in ('weekly','ramadan','thirteen'):
        limit=13 if selected_template=='thirteen' else 7
        try:
            template_day=int(request.GET.get('template_day','1'))
        except (TypeError,ValueError):
            template_day=1
        if template_day not in range(limit+1):
            template_day=1
        if selected_template=='thirteen':
            data,_=build_thirteen_days(sections)
            slots=[slot for slot in ORANGE_SLOTS if slot!='other']
            labels=ORANGE_LABELS
            template_days=[(i,f'روز {i}') for i in range(1,14)]
        elif selected_template=='weekly':
            data=build_orange_week(sections)
            slots=[slot for slot in ORANGE_SLOTS if slot!='other']
            labels=ORANGE_LABELS
            template_days=list(enumerate(ORANGE_DAYS,start=1))
        else:
            data=build_ramadan_week(sections)
            slots=[slot for slot in RAMADAN_SLOTS if slot!='other']
            labels=RAMADAN_LABELS
            template_days=list(enumerate(ORANGE_DAYS,start=1))
        for slot in slots:
            manual=next((row for row in sections if row.meal_slot==slot and row.day_number==template_day),None)
            rows=([card for card in data.get(template_day,[]) if card['slot']==slot] if template_day else [])
            template_rows.append({
                'slot':slot,'name':labels[slot],'manual':bool(manual),
                'body':manual.body if manual else '\n'.join(card['body'] for card in rows),
                'photo':next((m.url for m in manual.media.all() if m.kind=='image' and m.url),'') if manual else
                    next((card.get('photo','') for card in rows if card.get('photo')),''),
                'kcal':manual.estimated_kcal if manual else None,
            })
    return render(request,'core/treatment_content_manage.html',{
        'content':content,'sections':sections,'day_audios':list(content.daily_audio.all()),
        'template_rows':template_rows,'template_day':template_day,
        'template_days':template_days,
        'orange_only':orange_only,'orange_day':orange_day,
        'orange_days':list(enumerate(ORANGE_DAYS,start=1)),'orange_rows':orange_rows,
    })
