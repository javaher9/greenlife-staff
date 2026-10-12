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
    TreatmentCatalogItem, TreatmentRichContent, TreatmentRichSection, TreatmentRichMedia,
)
from .treatment_content_service import import_five_sample_zip

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
    sections=list(content.sections.prefetch_related('media').all())
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
                messages.success(request,'وضعیت محتوا ذخیره شد.')
            elif action=='update_content':
                content.intro_warning=request.POST.get('intro_warning','')[:8000]
                content.cover_external_url=request.POST.get('cover_external_url','')[:1300]
                content.audio_external_url=request.POST.get('audio_external_url','')[:1300]
                content.full_clean()
                content.save()
                messages.success(request,'اطلاعات عمومی ذخیره شد.')
            elif action=='save_section':
                section=get_object_or_404(content.sections,pk=request.POST.get('section_id'))
                section.title=(request.POST.get('title') or '').strip()[:200]
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
                content.sections.create(title=title,body='',sort_order=min(max_order+10,9999))
                messages.success(request,'بخش جدید افزوده شد.')
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
                else:
                    section=get_object_or_404(content.sections,pk=request.POST.get('section_id'))
                    position=(section.media.order_by('-sort_order').values_list('sort_order',flat=True).first() or 0)+10
                    media=TreatmentRichMedia(section=section,kind=kind,sort_order=min(position,9999))
                    media.uploaded_file.save(file.name,file,save=True)
                messages.success(request,'فایل روی سرور ذخیره شد.')
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
    return render(request,'core/treatment_content_manage.html',{
        'content':content,'sections':sections,
    })
