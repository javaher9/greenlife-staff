import base64
import json
import mimetypes
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openai import OpenAI
from django.utils import timezone


def _extract_json_object(raw):
    cleaned=(raw or '').strip()
    if cleaned.startswith('```'):
        cleaned=re.sub(r'^```(?:json)?\s*','',cleaned,flags=re.IGNORECASE)
        cleaned=re.sub(r'\s*```$','',cleaned).strip()
    if not cleaned.startswith('{'):
        start=cleaned.find('{'); end=cleaned.rfind('}')
        if start!=-1 and end>start:
            cleaned=cleaned[start:end+1]
    data=json.loads(cleaned)
    if not isinstance(data,dict):
        raise ValueError('پاسخ تحلیل باید یک JSON object باشد.')
    return data


def _decimal_from_vision(value):
    if value in (None,''): return None
    digits=str(value).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789'))
    digits=re.sub(r'[^0-9.-]','',digits)
    try: return Decimal(digits)
    except (InvalidOperation,ValueError): return None


def analyze_finance_receipt(transaction):
    """Extract receipt facts without ever replacing the consultant's amount."""
    key=os.getenv('OPENAI_API_KEY','').strip()
    if not key:
        transaction.analysis_status='skipped'
        transaction.analysis_error='OPENAI_API_KEY تنظیم نشده است.'
        transaction.save(update_fields=['analysis_status','analysis_error'])
        return False,'تحلیل تصویر روی سرور تنظیم نشده است.'
    if not transaction.receipt_image:
        transaction.analysis_status='failed'
        transaction.analysis_error='تصویر تراکنش وجود ندارد.'
        transaction.save(update_fields=['analysis_status','analysis_error'])
        return False,transaction.analysis_error

    try:
        transaction.receipt_image.open('rb')
        try: image_bytes=transaction.receipt_image.read()
        finally: transaction.receipt_image.close()
        if not image_bytes: raise ValueError('تصویر تراکنش خالی است.')

        encoded=base64.b64encode(image_bytes).decode('ascii')
        prompt=(
            'این تصویر یک رسید مالی کلینیک است. فقط اطلاعاتی را که واقعاً در تصویر '
            'قابل خواندن است استخراج کن و هیچ عددی را حدس نزن. خروجی فقط JSON معتبر '
            'با کلیدهای readable (boolean)، document_type (pos_receipt, bank_transfer, '
            'bank_screenshot, other)، detected_amount (عدد یا null)، currency_unit '
            '(rial, toman, unknown)، detected_date (متن یا null)، tracking_number '
            '(متن یا null)، destination_card_last4 (متن یا null)، payer_or_payee '
            '(متن یا null)، destination_evidence (نام بانک، پذیرنده، کارت یا نشانه مقصد '
            'که در تصویر دیده می‌شود؛ متن یا null)، confidence (high, medium, low)، '
            'warnings (آرایه متن) باشد. اطلاعاتی که خوانا نیست null باشد. مقصدی که '
            f'کاربر در فرم انتخاب کرده «{transaction.payment_method}» است؛ آن را تغییر نده.'
        )
        client=OpenAI(api_key=key,timeout=35,max_retries=1)
        response=client.responses.create(
            model=os.getenv('OPENAI_VISION_MODEL',os.getenv('OPENAI_ANALYSIS_MODEL','gpt-4.1-mini')),
            input=[{'role':'user','content':[
                {'type':'input_text','text':prompt},
                {'type':'input_image','image_url':f'data:image/webp;base64,{encoded}'},
            ]}],
        )
        raw=(getattr(response,'output_text','') or '').strip()
        if not raw: raise ValueError('پاسخ تحلیل تصویر خالی بود.')
        data=_extract_json_object(raw)

        warnings=data.get('warnings',[])
        if not isinstance(warnings,list): warnings=[str(warnings)] if warnings else []
        data['warnings']=[str(x)[:240] for x in warnings][:10]
        detected=_decimal_from_vision(data.get('detected_amount'))
        unit=str(data.get('currency_unit') or 'unknown').lower()
        manual=Decimal(transaction.amount)
        normalized=None; matches=None
        if detected is not None:
            if unit=='toman': normalized=detected*10
            elif unit=='rial': normalized=detected
            else:
                if detected==manual: normalized=detected
                elif detected*10==manual: normalized=detected*10
            if normalized is not None: matches=normalized==manual
        data['detected_amount']=str(detected) if detected is not None else None
        data['selected_destination']=transaction.payment_method
        data['normalized_amount_rial']=str(normalized) if normalized is not None else None
        data['manual_amount_match']=matches
        if matches is False:
            data['warnings'].insert(0,'اختلاف مبلغ: عدد خوانده‌شده از تصویر با مبلغ دستی یکسان نیست؛ مدیر بررسی کند.')
        document_type=str(data.get('document_type') or '')
        destination_type_match=None
        if transaction.payment_method.startswith('Pos '):
            destination_type_match=document_type=='pos_receipt'
        elif transaction.payment_method.startswith('CC '):
            destination_type_match=document_type in ('bank_transfer','bank_screenshot')
        data['destination_type_match']=destination_type_match
        if destination_type_match is False:
            data['warnings'].insert(0,'نوع رسید با مقصد انتخاب‌شده در فرم هم‌خوان نیست؛ مدیر بررسی کند.')

        transaction.receipt_analysis=data
        transaction.analysis_status='processed'
        transaction.analysis_error=''
        transaction.analyzed_at=timezone.now()
        transaction.save(update_fields=['receipt_analysis','analysis_status','analysis_error','analyzed_at'])
        if matches is False: return True,'تصویر تحلیل شد؛ اختلاف مبلغ برای بررسی مدیر علامت‌گذاری شد.'
        return True,'تصویر تراکنش فشرده و تحلیل شد.'
    except Exception as exc:
        transaction.analysis_status='failed'
        transaction.analysis_error=str(exc)[:500]
        transaction.save(update_fields=['analysis_status','analysis_error'])
        return False,f'تحلیل تصویر انجام نشد: {exc}'


def _audio_upload_tuple(field_file):
    """Convert a Django FieldFile to a file payload accepted by openai-python.

    Django's FieldFile.open() returns the FieldFile itself. Newer versions of
    openai-python validate upload types and reject Django FieldFile objects.
    Reading the bytes and sending a standard (filename, bytes, content_type)
    tuple avoids that incompatibility and works with local or remote storage.
    """
    field_file.open("rb")
    try:
        data = field_file.read()
    finally:
        field_file.close()

    if not data:
        raise ValueError("فایل صوتی خالی است.")

    filename = Path(field_file.name or "report-audio.webm").name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return (filename, data, content_type)


def process_report(report):
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return False, "OPENAI_API_KEY تنظیم نشده است."

    client = OpenAI(api_key=key)
    source_text = (report.text or "").strip()

    try:
        if report.audio:
            audio_payload = _audio_upload_tuple(report.audio)
            result = client.audio.transcriptions.create(
                model=os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"),
                file=audio_payload,
                language="fa",
            )
            report.transcript = getattr(result, "text", "") or ""
            source_text = (source_text + "\n" + report.transcript).strip()

        if not source_text:
            return False, "گزارش متنی یا صوتی ندارد."

        prompt = (
            "گزارش روزانه یک کارمند کلینیک را تحلیل کن. خروجی فقط JSON معتبر فارسی "
            "با کلیدهای summary (خلاصه کوتاه)، tags (آرایه برچسب‌ها)، follow_up "
            "(اقدام‌های پیگیری) باشد. اطلاعات پزشکی حساس یا نام بیمار را تکرار نکن. متن:\n"
            + source_text
        )
        response = client.responses.create(
            model=os.getenv("OPENAI_ANALYSIS_MODEL", "gpt-4.1-mini"),
            input=prompt,
        )

        raw = (getattr(response, "output_text", "") or "").strip()
        if not raw:
            raise ValueError(
                "پاسخ تحلیل هوش مصنوعی خالی بود. "
                "OPENAI_API_KEY، مدل OPENAI_ANALYSIS_MODEL و دسترسی اینترنت کانتینر را بررسی کنید."
            )

        # Some models/SDK versions may wrap valid JSON in Markdown fences.
        # Normalize that before parsing so a harmless ```json wrapper does not
        # break report processing.
        try:
            data = _extract_json_object(raw)
        except json.JSONDecodeError as exc:
            preview = raw.replace("\\n", " ")[:220]
            raise ValueError(
                "پاسخ تحلیل AI فرمت JSON معتبر نداشت. "
                f"پاسخ دریافتی: {preview or '[خالی]'}"
            ) from exc

        summary = data.get("summary", "")
        tags = data.get("tags", [])
        follow_up = data.get("follow_up", "")

        if not isinstance(tags, list):
            tags = [str(tags)] if tags else []

        report.ai_summary = str(summary or "")
        report.ai_tags = [str(tag) for tag in tags]
        report.follow_up = str(follow_up or "")
        report.process_status = "processed"
        report.save()
        return True, "پردازش شد."

    except Exception as exc:
        # Keep the report/voice intact, but expose a concise error to the UI and
        # mark the record failed so it can be retried after configuration fixes.
        report.process_status = "failed"
        report.save(update_fields=["process_status"])
        return False, str(exc)
