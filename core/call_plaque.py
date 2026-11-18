"""Validation and explainable readiness rules for call plaques (not probability)."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import LeadCallProfile

SCHEMA_VERSION = 1
ANSWER_STATES = {'unasked', 'answered', 'declined', 'not_applicable'}
ANSWER_KEYS = {'goal', 'priority', 'timing', 'barrier', 'interest', 'budget_fit', 'height_cm', 'weight_kg'}
ENUMS = {
    'timing': {'exploring': 'فعلاً آشنایی', 'later': 'بعداً', 'soon': 'در آینده نزدیک', 'now': 'آماده بررسی اکنون'},
    'barrier': {'none': 'مانع مشخصی ندارد', 'cost': 'هزینه', 'time': 'زمان', 'distance': 'فاصله', 'uncertainty': 'نیاز به اطلاعات بیشتر', 'consult': 'مشورت با دیگری', 'other': 'سایر'},
    'interest': {
        '1': 'فعلاً تمایلی ندارد', '2': 'فقط مایل به شنیدن معرفی است',
        '3': 'درباره خدمت سؤال مشخصی دارد', '4': 'می‌خواهد گزینه‌ها یا زمان‌ها را بررسی کند',
        '5': 'خودش درخواست قدم بعدی کرده است',
    },
    'budget_fit': {
        '1': 'هزینه فعلاً خارج از بودجه است', '2': 'فقط با کاهش هزینه قابل بررسی است',
        '3': 'باید مبلغ را با بودجه‌اش بسنجد', '4': 'با شرایط پرداخت موردنظرش قابل تأمین است',
        '5': 'مبلغ اعلام‌شده در بودجه‌اش است',
        # Original categorical responses remain readable without inventing a star rating.
        'suitable': 'هزینه اعلام‌شده مناسب است', 'needs_review': 'نیاز به بررسی هزینه',
        'not_suitable': 'هزینه اعلام‌شده مناسب نیست',
    },
}
COMMUNICATION_STYLES = {
    'unknown': 'هنوز مشخص نیست', 'direct': 'خلاصه و نتیجه‌محور', 'details': 'جزئیات و روش کار',
    'social': 'گفت‌وگو و تجربه مراجعه', 'support': 'آرام و مرحله‌به‌مرحله', 'mixed': 'ترکیبی',
}
OUTCOMES = {
    'answered': 'گفت‌وگو انجام شد', 'no_answer': 'پاسخ نداد', 'follow_up': 'پیگیری با اجازه',
    'not_interested': 'فعلاً تمایل ندارد', 'wrong_number': 'شماره یا مخاطب اشتباه', 'do_not_contact': 'درخواست عدم تماس',
}
CONSENTS = {'unknown', 'yes', 'no'}
DATA_KEYS = {'answers', 'outcome', 'whatsapp_consent', 'followup_consent', 'followup_at', 'operator_rating',
             'operator_reason', 'communication_style', 'communication_evidence', 'notes', 'do_not_contact'}
RESTRICTED_ANSWER_KEYS = {'timing', 'barrier'}


def empty_data():
    return {
        'answers': {key: {'state': 'unasked', 'value': ''} for key in sorted(ANSWER_KEYS)},
        'outcome': '', 'whatsapp_consent': 'unknown', 'followup_consent': 'unknown', 'followup_at': None,
        'operator_rating': None, 'operator_reason': '', 'communication_style': 'unknown',
        'communication_evidence': '', 'notes': '', 'do_not_contact': False,
    }


def _text(value, limit, field):
    if not isinstance(value, str) or len(value) > limit:
        raise ValidationError(f'مقدار «{field}» معتبر نیست یا بیش از حد طولانی است.')
    return value.strip()


def normalize_data(raw, *, final=False):
    if not isinstance(raw, dict) or set(raw) - DATA_KEYS:
        raise ValidationError('ساختار اطلاعات پلاک تماس معتبر نیست.')
    result = empty_data()
    answers = raw.get('answers', {})
    if not isinstance(answers, dict) or set(answers) - ANSWER_KEYS:
        raise ValidationError('سؤال ثبت‌شده معتبر نیست.')
    for key, answer in answers.items():
        if not isinstance(answer, dict) or set(answer) - {'state', 'value'}:
            raise ValidationError('ساختار پاسخ سؤال معتبر نیست.')
        state = answer.get('state', 'unasked')
        if state not in ANSWER_STATES:
            raise ValidationError('وضعیت پاسخ سؤال معتبر نیست.')
        value = answer.get('value', '')
        if state != 'answered':
            value = ''
        elif key in ENUMS:
            if not isinstance(value, str) or value not in ENUMS[key]:
                raise ValidationError('گزینه پاسخ سؤال معتبر نیست.')
        elif key in ('height_cm', 'weight_kg'):
            if isinstance(value, bool):
                raise ValidationError('قد یا وزن معتبر نیست.')
            try:
                value = Decimal(str(value).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')))
                low, high = (30, 260) if key == 'height_cm' else (2, 500)
                if not value.is_finite() or not low <= value <= high:
                    raise ValueError()
                value = str(value.quantize(Decimal('0.1')))
            except (InvalidOperation, ValueError, TypeError):
                raise ValidationError('قد یا وزن در محدوده معتبر وارد نشده است.')
        else:
            value = _text(value, 400, key)
            if not value:
                raise ValidationError('برای پاسخ داده‌شده، مقدار پاسخ را وارد کنید.')
        result['answers'][key] = {'state': state, 'value': value}
    outcome = raw.get('outcome', '')
    if not isinstance(outcome, str) or (outcome and outcome not in OUTCOMES) or (final and not outcome):
        raise ValidationError('نتیجه واقعی تماس را انتخاب کنید.')
    result['outcome'] = outcome
    for key in ('whatsapp_consent', 'followup_consent'):
        value = raw.get(key, 'unknown')
        if value not in CONSENTS:
            raise ValidationError('وضعیت اجازه مخاطب معتبر نیست.')
        result[key] = value
    flag = raw.get('do_not_contact', False)
    if not isinstance(flag, bool):
        raise ValidationError('وضعیت عدم تماس معتبر نیست.')
    result['do_not_contact'] = flag or outcome == 'do_not_contact'
    if result['do_not_contact'] and (result['followup_consent'] == 'yes' or result['whatsapp_consent'] == 'yes'):
        raise ValidationError('درخواست عدم تماس با اجازه ارسال یا پیگیری سازگار نیست؛ پاسخ واقعی مخاطب را بررسی کنید.')
    followup = raw.get('followup_at')
    if followup:
        if not isinstance(followup, str) or len(followup) > 50:
            raise ValidationError('زمان پیگیری معتبر نیست.')
        parsed = parse_datetime(followup)
        if parsed is None:
            raise ValidationError('زمان پیگیری معتبر نیست.')
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        if result['followup_consent'] != 'yes' or result['do_not_contact']:
            raise ValidationError('تعیین زمان پیگیری به اجازه روشن مخاطب نیاز دارد.')
        if final and (parsed < timezone.now() - timedelta(minutes=5) or parsed > timezone.now() + timedelta(days=730)):
            raise ValidationError('زمان پیگیری باید در آینده و حداکثر دو سال بعد باشد.')
        result['followup_at'] = timezone.localtime(parsed).isoformat()
    if final and outcome == 'follow_up' and (result['followup_consent'] != 'yes' or not result['followup_at']):
        raise ValidationError('برای ثبت پیگیری، اجازه مخاطب و روز و ساعت توافق‌شده لازم است.')
    if outcome in ('no_answer', 'wrong_number') and (result['whatsapp_consent'] == 'yes' or result['followup_consent'] == 'yes'):
        raise ValidationError('وقتی گفت‌وگویی با مخاطب انجام نشده، رضایت تازه ثبت نکنید.')
    rating = raw.get('operator_rating')
    if rating is not None and (isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5):
        raise ValidationError('ارزیابی کارشناس باید از ۱ تا ۵ باشد.')
    result['operator_rating'] = rating
    result['operator_reason'] = _text(raw.get('operator_reason', ''), 400, 'دلیل ارزیابی')
    result['communication_evidence'] = _text(raw.get('communication_evidence', ''), 400, 'شاهد ترجیح ارتباط')
    result['notes'] = _text(raw.get('notes', ''), 2000, 'یادداشت')
    style = raw.get('communication_style', 'unknown')
    if not isinstance(style, str) or style not in COMMUNICATION_STYLES:
        raise ValidationError('ترجیح ارتباط معتبر نیست.')
    result['communication_style'] = style
    if final and rating is not None and not result['operator_reason']:
        raise ValidationError('برای ارزیابی کارشناس یک دلیل کوتاه ثبت کنید.')
    if final and style != 'unknown' and not result['communication_evidence']:
        raise ValidationError('برای ترجیح ارتباط، پاسخ یا مشاهده کوتاه واقعی ثبت کنید.')
    if final and outcome in ('no_answer', 'wrong_number'):
        if (any(item['state'] != 'unasked' for item in result['answers'].values())
                or rating is not None or style != 'unknown'
                or result['whatsapp_consent'] != 'unknown' or result['followup_consent'] != 'unknown'
                or result['do_not_contact']):
            raise ValidationError('بدون گفت‌وگو با مخاطب، پاسخ، ارزیابی یا اجازه تازه ثبت نمی‌شود. اطلاعات قبلی در سوابق محفوظ است.')
    return result


def merge_profile(previous, current):
    """Unasked questions preserve earlier evidence; declined answers supersede it."""
    if current['outcome'] == 'no_answer' and previous:
        merged = deepcopy(previous)
        merged['outcome'] = current['outcome']
        merged['notes'] = current['notes']
        return merged
    merged = deepcopy(current)
    merged['answers'] = deepcopy(previous.get('answers', empty_data()['answers']))
    for key, answer in current['answers'].items():
        if answer['state'] != 'unasked':
            merged['answers'][key] = deepcopy(answer)
    # A later unanswered call does not invent a new assessment or erase the last one.
    for value_key, reason_key, unknown in (
        ('operator_rating', 'operator_reason', None),
        ('communication_style', 'communication_evidence', 'unknown'),
    ):
        if current[value_key] == unknown and previous.get(value_key) not in (None, '', 'unknown'):
            merged[value_key] = previous[value_key]
            merged[reason_key] = previous.get(reason_key, '')
    return merged


def score_readiness(data, *, do_not_contact=False):
    """Version-one rule score. Medical measures, wealth and DISC are never inputs."""
    if do_not_contact:
        return {'score': 0, 'band': 'stop', 'label': 'عدم تماس', 'reasons': ['مخاطب درخواست توقف ارتباط داده است.'], 'confidence': 'ثبت صریح', 'version': SCHEMA_VERSION}
    if data.get('outcome') == 'wrong_number':
        return {'score': None, 'band': 'unknown', 'label': 'شماره نیازمند بررسی', 'reasons': ['هویت یا شماره مخاطب تأیید نشده است.'], 'confidence': 'اطلاعات ناکافی', 'version': SCHEMA_VERSION}
    answers = data.get('answers', {})
    observed = {key: item['value'] for key, item in answers.items() if item.get('state') == 'answered' and key in ('goal', 'priority', 'timing', 'barrier')}
    if len(observed) < 2:
        return {'score': None, 'band': 'unknown', 'label': 'اطلاعات ناکافی', 'reasons': ['برای ارزیابی، دست‌کم دو پاسخ مرتبط لازم است.'], 'confidence': 'اطلاعات ناکافی', 'version': SCHEMA_VERSION}
    score, reasons = 0, []
    if observed.get('goal'):
        score += 20
        reasons.append('موضوع مورد علاقه مخاطب مشخص شده است.')
    if observed.get('priority'):
        score += 15
        reasons.append('اولویت مخاطب با پاسخ خودش ثبت شده است.')
    if observed.get('timing'):
        value = observed['timing']
        score += {'exploring': 0, 'later': 5, 'soon': 15, 'now': 20}[value]
        reasons.append('زمان تصمیم: ' + ENUMS['timing'][value])
    if observed.get('barrier'):
        value = observed['barrier']
        score += {'none': 15, 'cost': 0, 'time': 3, 'distance': 3, 'uncertainty': 5, 'consult': 5, 'other': 0}[value]
        reasons.append('مانع اعلام‌شده: ' + ENUMS['barrier'][value])
    if data.get('followup_consent') == 'yes' and data.get('followup_at'):
        score += 30
        reasons.append('قدم بعدی با اجازه و زمان مشخص توافق شده است.')
    elif data.get('whatsapp_consent') == 'yes':
        score += 10
        reasons.append('برای دریافت معرفی اجازه داده است؛ اجازه تماس بعدی جداست.')
    if data.get('outcome') == 'not_interested':
        score = min(score, 15)
        reasons.append('در آخرین گفت‌وگو فعلاً تمایل نداشته است.')
    if score < 20:
        band, label = 'red', 'آمادگی پایین'
    elif score < 40:
        band, label = 'yellow', 'در حال بررسی'
    elif score < 60:
        band, label = 'green', 'علاقه مشخص'
    elif score < 80:
        band, label = 'blue', 'آمادگی بیشتر'
    else:
        band, label = 'purple', 'آماده اقدام با اجازه'
    return {'score': min(score, 100), 'band': band, 'label': label, 'reasons': reasons,
            'confidence': 'اطلاعات محدود' if len(observed) == 2 else 'اطلاعات متوسط' if len(observed) == 3 else 'اطلاعات تکمیل‌تر',
            'version': SCHEMA_VERSION}


def safe_data(data, *, restricted=False):
    if not restricted:
        return deepcopy(data)
    # Allowlisted enums only: free text could itself contain phone/medical/financial details.
    return {
        'answers': {key: deepcopy(value) for key, value in data.get('answers', {}).items() if key in RESTRICTED_ANSWER_KEYS},
        'outcome': data.get('outcome', ''), 'whatsapp_consent': data.get('whatsapp_consent', 'unknown'),
        'followup_consent': data.get('followup_consent', 'unknown'), 'followup_at': data.get('followup_at'),
        'communication_style': data.get('communication_style', 'unknown'),
        'do_not_contact': bool(data.get('do_not_contact', False)),
    }


def lead_do_not_contact(lead):
    """Use select_related('call_profile') in loops, or the bulk helper below."""
    try:
        return lead.call_profile.do_not_contact
    except LeadCallProfile.DoesNotExist:
        return False


def call_plaque_summaries(leads_or_ids):
    ids = [getattr(item, 'pk', item) for item in leads_or_ids]
    result = {}
    for row in LeadCallProfile.objects.filter(lead_id__in=ids).only('lead_id', 'readiness', 'do_not_contact'):
        value = row.readiness or score_readiness({}, do_not_contact=row.do_not_contact)
        result[row.lead_id] = {key: value.get(key) for key in ('score', 'band', 'label', 'confidence')}
        result[row.lead_id]['do_not_contact'] = row.do_not_contact
    return result
