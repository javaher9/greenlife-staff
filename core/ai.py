import json
import mimetypes
import os
from pathlib import Path

from openai import OpenAI


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
        raw = response.output_text.strip()
        data = json.loads(raw)

        report.ai_summary = data.get("summary", "")
        report.ai_tags = data.get("tags", [])
        report.follow_up = data.get("follow_up", "")
        report.process_status = "processed"
        report.save()
        return True, "پردازش شد."

    except Exception as exc:
        # Keep the report/voice intact, but expose a concise error to the UI and
        # mark the record failed so it can be retried after configuration fixes.
        report.process_status = "failed"
        report.save(update_fields=["process_status"])
        return False, str(exc)
