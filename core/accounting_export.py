"""Read-only source feeds for the independent Green Life accounting service."""

import logging
import re
from datetime import date, datetime, time
from decimal import Decimal
from hashlib import sha256
from hmac import compare_digest

from django.conf import settings
from django.db.models import Exists, F, OuterRef
from django.http import FileResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from core.models import FinancialTransaction
from payments.models import PaymentEvent, PaymentRequest

logger = logging.getLogger(__name__)
AUTHORIZED_RECEIPT_CODES = frozenset({'POS-S', 'CC-G'})
# Staff stores these historical spellings for the same two destinations.
_RECEIPT_CODE_MAP = {
    'Pos S': 'POS-S', 'POS-S': 'POS-S',
    'CC G': 'CC-G', 'CC-G': 'CC-G', 'CCG': 'CC-G',
}
_PAGE_SIZE = 100
_MAX_ID = 2**63 - 1


def _access_error(request, feed):
    digest = getattr(settings, 'ACCOUNTING_EXPORT_TOKEN_SHA256', '')
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        return JsonResponse({'error': 'not_found'}, status=404)
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if not (
        request.is_secure() and scheme.lower() == 'bearer' and token
        and compare_digest(sha256(token.encode()).hexdigest(), digest)
    ):
        logger.warning('Accounting export denied feed=%s', feed)
        return JsonResponse({'error': 'forbidden'}, status=403)
    return None


def _window(request):
    """A replayable Tehran date interval with an exclusive end date."""
    since_raw = request.GET['from']
    until_raw = request.GET['until']
    since, until = date.fromisoformat(since_raw), date.fromisoformat(until_raw)
    if since.isoformat() != since_raw or until.isoformat() != until_raw:
        raise ValueError
    if not 0 < (until - since).days <= 31:
        raise ValueError
    after = int(request.GET.get('after', '0'))
    if not 0 <= after <= _MAX_ID:
        raise ValueError
    staff_zone = timezone.get_default_timezone()
    return (
        timezone.make_aware(datetime.combine(since, time.min), staff_zone),
        timezone.make_aware(datetime.combine(until, time.min), staff_zone),
        after,
    )


def _receipts(start, end, after):
    stored_codes = [
        code for code, canonical in _RECEIPT_CODE_MAP.items()
        if canonical in AUTHORIZED_RECEIPT_CODES
    ]
    return FinancialTransaction.objects.filter(
        pk__gt=after, occurred_at__gte=start, occurred_at__lt=end,
        entry_type='inc', review_status='approved', payment_method__in=stored_codes,
        cash_currency__in=('', 'IRR'), amount__gt=0,
    ).values('pk', 'occurred_at', 'amount', 'payment_method', 'branch_id').order_by('pk')


def _expenses():
    approval = PaymentEvent.objects.filter(
        payment_id=OuterRef('pk'), action='approve', actor_id=OuterRef('approved_by_id'),
    )
    return PaymentRequest.objects.filter(
        Exists(approval), state='paid', kind__in=('payment', 'personal_expense'),
        cost_owner='company', approved_by__isnull=False, approved_at__isnull=False,
        paid_at__gte=F('approved_at'), amount_toman__gt=0,
    ).only(
        'pk', 'approved_at', 'paid_at', 'amount_toman', 'branch_id', 'category',
        'cost_center', 'payment_reference', 'description',
        'personal_expense_receipt', 'payment_receipt',
    )


def _date(value):
    return timezone.localtime(value, timezone.get_default_timezone()).date().isoformat()


def _receipt_row(row):
    return {
        'source_id': f"staff:receipt:{row['pk']}",
        'date': _date(row['occurred_at']),
        'code': _RECEIPT_CODE_MAP[row['payment_method']],
        'amount_rial': str(row['amount'].to_integral_value()),
        'branch_id': row['branch_id'],
    }


def _expense_row(row):
    return {
        'source_id': f'staff:expense:{row.pk}',
        'approved_at': row.approved_at.isoformat(),
        'paid_at': row.paid_at.isoformat(),
        'amount_rial': str(Decimal(row.amount_toman) * Decimal(10)),
        'category': row.category,
        'cost_center': row.cost_center,
        'branch_id': row.branch_id,
        'documents': {
            kind: reverse(f'accounting_expense_{kind}', args=[row.pk])
            for kind in ('invoice', 'receipt')
        },
    }


def _document_available(field):
    if not field:
        return False
    try:
        return field.storage.exists(field.name)
    except OSError:
        logger.warning('Accounting expense document storage unavailable')
        return False


def _expense_complete(row):
    return (
        row.description.strip() and row.payment_reference.strip()
        and _document_available(row.personal_expense_receipt)
        and _document_available(row.payment_receipt)
    )


@never_cache
@require_GET
def export_feed(request, feed):
    denied = _access_error(request, feed)
    if denied is not None:
        return denied
    try:
        start, end, after = _window(request)
    except (KeyError, ValueError, OverflowError):
        return JsonResponse({'error': 'invalid_window'}, status=400)

    if feed == 'receipts':
        page = list(_receipts(start, end, after)[:_PAGE_SIZE + 1])
        complete = [
            row for row in page[:_PAGE_SIZE]
            if row['amount'] == row['amount'].to_integral_value()
        ]
        items = [_receipt_row(row) for row in complete]
        last_id = page[_PAGE_SIZE - 1]['pk'] if len(page) > _PAGE_SIZE else None
    else:
        page = list(_expenses().filter(
            pk__gt=after, paid_at__gte=start, paid_at__lt=end,
        ).order_by('pk')[:_PAGE_SIZE + 1])
        items = [_expense_row(row) for row in page[:_PAGE_SIZE] if _expense_complete(row)]
        last_id = page[_PAGE_SIZE - 1].pk if len(page) > _PAGE_SIZE else None

    skipped = min(len(page), _PAGE_SIZE) - len(items)
    logger.info('Accounting export feed=%s rows=%d incomplete=%d', feed, len(items), skipped)
    return JsonResponse({
        'version': 1, 'source': 'greenlife-staff', 'feed': feed, 'currency': 'IRR',
        'items': items, 'incomplete_count': skipped, 'next_after': last_id,
    })


@never_cache
@require_GET
def expense_document(request, pk, kind):
    denied = _access_error(request, 'expense-document')
    if denied is not None:
        return denied

    field_name = {'invoice': 'personal_expense_receipt', 'receipt': 'payment_receipt'}[kind]
    row = _expenses().filter(pk=pk).first()
    if row is None or not _expense_complete(row):
        return JsonResponse({'error': 'not_found'}, status=404)
    try:
        handle = getattr(row, field_name).open('rb')
    except FileNotFoundError:
        return JsonResponse({'error': 'not_found'}, status=404)
    response = FileResponse(
        handle, as_attachment=True, filename=f'{kind}.bin',
        content_type='application/octet-stream',
    )
    response['X-Content-Type-Options'] = 'nosniff'
    logger.info('Accounting expense document exported kind=%s', kind)
    return response
