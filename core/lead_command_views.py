from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET
from .views import executive_required

AGENTS = [
    ("commander","Lead Commander","فرمانده لید","جمع‌بندی و اولویت‌بندی فرصت‌ها"),
    ("luxury","Luxury Lead Scout","شکارچی لید VIP","کشف کانال‌های پریمیوم و باکیفیت"),
    ("source","Lead Source Scout","کشف منابع","پیدا کردن منابع جدید قابل تست"),
    ("seo","Google / SEO Agent","گوگل و سئو","فرصت‌های High-Intent و صفحات تجاری"),
    ("instagram","Instagram Agent","اینستاگرام","بهبود ورودی و Qualification"),
    ("partner","Partnership Agent","پارتنرشیپ","کشف و ارزیابی شرکای مناسب"),
    ("quality","Lead Quality Agent","کیفیت لید","اندازه‌گیری کیفیت منبع تا فروش"),
]

def _snapshot():
    # V1 is intentionally honest: agents stay WAITING until a real worker writes heartbeats/events.
    now=timezone.now()
    agents=[{
        "key":key,"name":name,"fa":fa,"mission":mission,
        "status":"waiting","status_label":"WAITING",
        "activity":"در انتظار اتصال Worker واقعی",
        "heartbeat":None,
    } for key,name,fa,mission in AGENTS]
    return {
        "server_time":now.isoformat(),
        "live":True,
        "agents":agents,
        "kpi":{"agents":len(agents),"active":0,"qualified_today":0,"opportunities":0,"revenue_today":0},
        "events":[],
        "note":"هیچ فعالیت ساختگی نمایش داده نمی‌شود؛ Activity فقط پس از اتصال Worker واقعی ثبت خواهد شد.",
    }

@executive_required
def lead_command_center(request):
    return render(request,"core/lead_command_center.html",{"snapshot":_snapshot()})

@require_GET
@executive_required
def lead_command_center_live(request):
    return JsonResponse(_snapshot(),json_dumps_params={"ensure_ascii":False})
