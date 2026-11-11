"""Explicit manual-DM provenance, Tehran clock, and durable gap history."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .models import AuditLog, OperationsIncident, ReferralLead

TEHRAN = ZoneInfo('Asia/Tehran')


def record_manual_dm(lead, actor):
    AuditLog.objects.create(actor=actor,action='instagram_manual_created',path='/instagram/manual/',method='POST',
        object_type='ReferralLead',object_id=str(lead.pk),summary='Successful manual Instagram DM registration',
        metadata={'country_id':lead.country_id})
    reconcile_direct_gap()


def direct_gap(now=None, country_id=None):
    now=(now or timezone.now()).astimezone(TEHRAN)
    start=datetime.combine(now.date(),time(8),tzinfo=TEHRAN)
    if now < start:
        return None
    logs=AuditLog.objects.filter(action='instagram_manual_created',created_at__gte=start,created_at__lte=now)
    if country_id:
        logs=logs.filter(metadata__country_id=country_id)
    latest=logs.order_by('-created_at').values_list('created_at',flat=True).first()
    # Historical records already store the actual entry route. Never infer it
    # from Instagram group membership, mutable notes or updated_at.
    legacy=ReferralLead.objects.filter(source='panel',created_at__gte=start,created_at__lte=now).filter(
        Q(source_url__endswith='/instagram/manual/') | Q(source_url__startswith='instagram/operator/')
    )
    if country_id:
        legacy=legacy.filter(country_id=country_id)
    legacy_latest=legacy.order_by('-created_at').values_list('created_at',flat=True).first()
    last=max([v for v in (latest,legacy_latest) if v],default=None)
    origin=max(start,last.astimezone(TEHRAN)) if last else start
    return {'active':now-origin>timedelta(hours=2),'origin':origin,'deadline':origin+timedelta(hours=2),'day':now.date()}


@transaction.atomic
def reconcile_direct_gap(now=None):
    from .models import Country
    now=now or timezone.now()
    # Scope by the same existing country workspaces; no personal operator blame.
    for country_id in Country.objects.filter(is_active=True).values_list('pk',flat=True):
        gap=direct_gap(now,country_id)
        if gap is None:
            continue
        key=f'direct:{country_id}:{gap["origin"].isoformat()}'
        # A new real manual event is the only resolution signal. Midnight alone
        # never resolves an earlier missed window; it remains historical.
        newer=AuditLog.objects.filter(action='instagram_manual_created',metadata__country_id=country_id,created_at__lte=now).order_by('-created_at').first()
        if newer:
            OperationsIncident.objects.filter(kind='manual_dm_gap',country_id=country_id,resolved_at__isnull=True,deadline__lt=newer.created_at).update(resolved_at=newer.created_at)
        if gap['active']:
            OperationsIncident.objects.get_or_create(key=key,defaults={
                'kind':'manual_dm_gap','country_id':country_id,'day':gap['day'],
                'started_at':gap['origin'],'deadline':gap['deadline'],
            })
