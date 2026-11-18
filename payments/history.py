"""Read-only, permission-scoped presentation of payment requests and their history."""

from pathlib import PurePosixPath
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q

from .models import PaymentEvent, PaymentRequest


DIGIT_TRANSLATION = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
EVENT_LABELS = {
    'created': 'ثبت درخواست',
    'approve': 'تأیید و ارجاع برای پرداخت',
    'reject': 'رد درخواست',
    'needs_info': 'درخواست توضیح بیشتر',
    'clarification_answered': 'ارسال توضیحات',
    'reassigned': 'تغییر مسئول پرداخت',
    'executive_edit': 'اصلاح مبلغ یا شرح',
    'executive_cancel': 'لغو درخواست',
    'executive_delete': 'حذف درخواست تکراری یا اشتباهی',
    'paid': 'ثبت پرداخت و رسید',
}


def visible_payments(user, is_executive):
    """The history never grants staff access to other people's financial records."""
    queryset = PaymentRequest.objects.all()
    if not user.is_authenticated or not user.is_active:
        return queryset.none()
    if not is_executive:
        queryset = queryset.filter(Q(requester=user) | Q(assigned_to=user))
    return queryset


def presentation_queryset(queryset):
    return queryset.select_related(
        'requester', 'assigned_to', 'approved_by', 'beneficiary', 'branch',
    ).annotate(
        history_cancelled=Exists(PaymentEvent.objects.filter(
            payment_id=OuterRef('pk'), action='executive_cancel',
        )),
        history_paid_event=Exists(PaymentEvent.objects.filter(
            payment_id=OuterRef('pk'), action='paid',
        )),
    )


def display_name(user):
    if not user:
        return 'تعیین نشده'
    full_name = user.get_full_name().strip()
    if full_name:
        return full_name
    if user.username.lower() in settings.EXECUTIVE_USERNAMES:
        return 'دکتر جواهریان'
    return user.username


def receipt_kind(receipt):
    """Classify for display only; thumbnail generation separately decodes the file."""
    if not receipt:
        return 'none'
    extension = PurePosixPath(receipt.name).suffix.lower()
    if extension in ('.jpg', '.jpeg', '.png', '.webp'):
        return 'image'
    if extension == '.pdf':
        return 'pdf'
    return 'file'


def decorate_payment(payment, is_executive):
    payment.history_state_label = (
        'لغو شده' if payment.state == 'rejected' and payment.history_cancelled
        else payment.get_state_display()
    )
    payment.requester_name = display_name(payment.requester)
    payment.assignee_name = display_name(payment.assigned_to)
    # An original invoice must not be presented as proof of the later payout.
    payment.receipt_kind = receipt_kind(payment.payment_receipt) if payment.state == 'paid' else 'none'
    payment.personal_receipt_kind = (
        receipt_kind(payment.personal_expense_receipt)
        if payment.kind == 'personal_expense' else 'none'
    )
    payment.history_can_edit = bool(
        is_executive and payment.state in ('pending', 'approved')
        and not payment.deleted_at and not payment.has_payment_evidence
    )
    payment.history_can_delete = bool(
        is_executive and not payment.deleted_at and not payment.has_payment_evidence
    )
    return payment


def _positive_id(raw):
    value = str(raw).strip().translate(DIGIT_TRANSLATION)
    if value.isascii() and value.isdecimal() and len(value) <= 19:
        number = int(value)
        if 0 < number <= 9223372036854775807:
            return number
    return None


def history_context(request, is_executive):
    authorized = visible_payments(request.user, is_executive)
    aggregates = {state: Count('pk', filter=Q(state=state)) for state, _ in PaymentRequest.STATES}
    stats = authorized.aggregate(
        total=Count('pk'), mine=Count('pk', filter=Q(requester=request.user)),
        assigned=Count('pk', filter=Q(assigned_to=request.user)), **aggregates,
    )
    requesters = (
        User.objects.filter(pk__in=authorized.values('requester_id'))
        .order_by('first_name', 'last_name', 'username', 'pk')
        if is_executive else User.objects.none()
    )
    filters = {
        'q': request.GET.get('q', '').strip()[:200],
        'status': request.GET.get('status', ''),
        'scope': request.GET.get('scope', 'all'),
        'requester': '',
        'receipt': request.GET.get('receipt', ''),
    }
    if filters['status'] not in dict(PaymentRequest.STATES):
        filters['status'] = ''
    if filters['scope'] not in ('all', 'mine', 'assigned'):
        filters['scope'] = 'all'
    if filters['receipt'] not in ('yes', 'no'):
        filters['receipt'] = ''
    requester_id = _positive_id(request.GET.get('requester', ''))
    if is_executive and requester_id and requesters.filter(pk=requester_id).exists():
        filters['requester'] = str(requester_id)

    filtered = authorized
    if filters['scope'] == 'mine':
        filtered = filtered.filter(requester=request.user)
    elif filters['scope'] == 'assigned':
        filtered = filtered.filter(assigned_to=request.user)
    if filters['status']:
        filtered = filtered.filter(state=filters['status'])
    if filters['requester']:
        filtered = filtered.filter(requester_id=filters['requester'])
    has_receipt = Q(state='paid') & ~Q(payment_receipt='')
    if filters['receipt'] == 'yes':
        filtered = filtered.filter(has_receipt)
    elif filters['receipt'] == 'no':
        filtered = filtered.exclude(has_receipt)

    # Token matching supports full names split across first_name/last_name.
    # Bound both search length and token count; all conditions stay inside the
    # authorized queryset and are applied before pagination.
    for term in filters['q'].split()[:10]:
        normalized = term.translate(DIGIT_TRANSLATION)
        predicate = Q()
        for value in {term, normalized}:
            predicate |= (
                Q(description__icontains=value) | Q(recipient_name__icontains=value)
                | Q(payment_reference__icontains=value) | Q(requester__first_name__icontains=value)
                | Q(requester__last_name__icontains=value) | Q(requester__username__icontains=value)
            )
        numeric_id = _positive_id(normalized.lstrip('#'))
        if numeric_id:
            predicate |= Q(pk=numeric_id)
        filtered = filtered.filter(predicate)

    ordered = presentation_queryset(filtered).order_by('-created_at', '-pk')
    page = Paginator(ordered, 25).get_page(request.GET.get('page', '1').translate(DIGIT_TRANSLATION))
    page.object_list = [decorate_payment(payment, is_executive) for payment in page.object_list]
    query = urlencode({
        key: value for key, value in filters.items()
        if value and not (key == 'scope' and value == 'all')
    })
    return {
        'history_page': page,
        'history_filters': filters,
        'history_requesters': requesters,
        'history_stats': stats,
        'history_query': query,
        'history_statuses': [(state, 'ردشده / لغوشده' if state == 'rejected' else label) for state, label in PaymentRequest.STATES],
    }
