"""The six values actually collected at GreenLife's scan station.

This is display-only: historic BodyAnalysisRecord columns and clinical source
are preserved. Missing historic measurements are blank, never inferred.
"""
from decimal import Decimal, InvalidOperation

SCAN_FIELDS=(
    ('weight_kg','وزن','kg'),
    ('inbody_score','امتیاز آنالیز',''),
    ('skeletal_muscle_kg','عضلات','kg'),
    ('fat_kg','چربی','kg'),
    ('whr','نسبت کمر به باسن',''),
    ('visceral_fat','چربی احشایی',''),
)


def scan_value(record,key):
    if record is None:
        return None
    if key in ('fat_kg','whr'):
        values=record.measurements or {}
        value=values.get(key) if isinstance(values,dict) else None
    else:
        value=getattr(record,key,None)
    if value in (None,''):
        return None
    try:
        parsed=Decimal(str(value))
        return parsed if parsed.is_finite() else None
    except (InvalidOperation,TypeError,ValueError):
        return None


def scan_summary(record):
    return [
        {'key':key,'label':label,'unit':unit,'value':scan_value(record,key)}
        for key,label,unit in SCAN_FIELDS
    ]


def scan_history_rows(records):
    return [
        {'date':record.recorded_at,'id':record.pk,'metrics':scan_summary(record)}
        for record in records
    ]
