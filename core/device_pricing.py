"""Shared device tariffs, preserving unconfigured legacy prices and plan snapshots."""
from decimal import Decimal, InvalidOperation
from .models import DeviceBaseTariff, DeviceTypeSchedule, TreatmentCatalogItem

MILLION = Decimal("1000000")


def to_toman_from_million(raw):
    value = str(raw if raw is not None else "").strip().replace(",", "")
    if not value:
        return None
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError("مبلغ معتبر نیست.")
    if not amount.is_finite() or amount < 0 or amount > Decimal("999999999"):
        raise ValueError("مبلغ باید عددی غیرمنفی باشد.")
    if amount != amount.quantize(Decimal("0.001")):
        raise ValueError("مبلغ باید حداکثر سه رقم اعشار داشته باشد.")
    toman = amount * MILLION
    if toman != toman.to_integral_value():
        raise ValueError("مبلغ باید حداکثر سه رقم اعشار داشته باشد.")
    return toman


def from_toman_to_million(raw):
    if raw is None:
        return ""
    value = format(Decimal(raw) / MILLION, "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def device_unit_price(name, branch=None):
    """Use bank price first; fall back to legacy catalog and shared base price."""
    title = (name or "").strip()
    kind = DeviceTypeSchedule.objects.filter(name__iexact=title).order_by("id").first()
    if kind and kind.unit_price_toman is not None:
        return kind.unit_price_toman
    legacy = TreatmentCatalogItem.objects.filter(
        category="device", name__iexact=title, is_active=True,
    )
    if branch:
        local = legacy.filter(branch=branch).order_by("sort_order", "id").first()
        if local and local.price_toman is not None:
            return local.price_toman
    shared = legacy.filter(branch__isnull=True).order_by("sort_order", "id").first()
    if shared and shared.price_toman is not None:
        return shared.price_toman
    return DeviceBaseTariff.current()
