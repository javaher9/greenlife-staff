"""SMS service built on the shared Greenlife API client."""
from .integration_api import ApiServerError, call_api
from .jalali import format_jalali
from .models import ApiServerSettings, SmsMessageLog, VisitAppointment


class SmsGatewayError(RuntimeError):
    def __init__(self,message,*,code='sms_error',http_status=None,payload=None):
        super().__init__(message)
        self.code=code
        self.http_status=http_status
        self.payload=payload


def _safe_payload(value):
    if isinstance(value,(dict,list,str,int,float,bool)) or value is None:
        return value
    return str(value)


def _record(*,number,body,purpose,status,created_by=None,appointment=None,
            provider_ids=None,http_status=None,error_code='',payload=None):
    return SmsMessageLog.objects.create(
        number=number,
        body=body,
        purpose=purpose,
        status=status,
        provider_ids=provider_ids or [],
        http_status=http_status,
        error_code=(error_code or '')[:120],
        response_payload=_safe_payload(payload) if payload is not None else {},
        appointment=appointment,
        created_by=created_by,
    )


def send_sms(number,body,*,purpose='manual',created_by=None,appointment=None,allow_disabled=False):
    number=(number or '').strip()
    body=(body or '').strip()
    if len(number)!=11 or not number.startswith('09') or not number.isdigit():
        raise SmsGatewayError('شماره موبایل معتبر نیست.',code='invalid_number')
    if not body:
        raise SmsGatewayError('متن پیام خالی است.',code='empty_body')
    try:
        http_status,payload=call_api(
            '/sms/send',{'body':body,'number':number},allow_disabled=allow_disabled,
        )
    except ApiServerError as exc:
        payload=exc.payload or {}
        _record(
            number=number,body=body,purpose=purpose,status='failed',created_by=created_by,
            appointment=appointment,http_status=exc.http_status,error_code=exc.code,payload=payload,
        )
        raise SmsGatewayError(
            str(exc),code=exc.code,http_status=exc.http_status,payload=payload,
        ) from exc

    provider_ids=payload.get('ids',[]) if isinstance(payload,dict) else []
    log=_record(
        number=number,body=body,purpose=purpose,status='accepted',created_by=created_by,
        appointment=appointment,provider_ids=provider_ids,http_status=http_status,payload=payload,
    )
    return log,payload


def send_appointment_confirmation(appointment_id):
    """Best-effort send: an SMS problem must never undo a valid appointment."""
    config=ApiServerSettings.load()
    if not (config.is_enabled and config.appointment_confirmation_enabled and config.is_configured):
        return None
    appointment=VisitAppointment.objects.select_related('branch','created_by').get(pk=appointment_id)
    try:
        body=config.appointment_message_template.format(
            name=appointment.full_name,
            branch=appointment.branch.name,
            date=format_jalali(appointment.appointment_date),
            time=appointment.appointment_time.strftime('%H:%M'),
        )
        return send_sms(
            appointment.phone,body,purpose='appointment',created_by=appointment.created_by,
            appointment=appointment,
        )
    except Exception:
        return None
