from datetime import date, datetime

PERSIAN_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
LATIN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def to_persian_digits(value):
    return str(value).translate(PERSIAN_DIGITS)


def _div(a, b): return a // b


def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0,31,59,90,120,151,181,212,243,273,304,334]
    if gy > 1600:
        jy = 979; gy -= 1600
    else:
        jy = 0; gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = 365*gy + _div(gy2+3,4) - _div(gy2+99,100) + _div(gy2+399,400) - 80 + gd + g_d_m[gm-1]
    jy += 33*_div(days,12053); days %= 12053
    jy += 4*_div(days,1461); days %= 1461
    if days > 365:
        jy += _div(days-1,365); days = (days-1)%365
    if days < 186:
        jm = 1 + _div(days,31); jd = 1 + days%31
    else:
        jm = 7 + _div(days-186,30); jd = 1 + (days-186)%30
    return jy, jm, jd


def jalali_to_gregorian(jy, jm, jd):
    if jy > 979:
        gy = 1600; jy -= 979
    else:
        gy = 621
    days = 365*jy + _div(jy,33)*8 + _div((jy%33)+3,4) + 78 + jd
    days += (jm-1)*31 if jm < 7 else (jm-7)*30 + 186
    gy += 400*_div(days,146097); days %= 146097
    if days > 36524:
        gy += 100*_div(days-1,36524); days = (days-1)%36524
        if days >= 365: days += 1
    gy += 4*_div(days,1461); days %= 1461
    if days > 365:
        gy += _div(days-1,365); days = (days-1)%365
    gd = days + 1
    sal_a = [0,31,29 if (gy%4==0 and gy%100!=0) or gy%400==0 else 28,31,30,31,30,31,31,30,31,30,31]
    gm = 1
    while gm <= 12 and gd > sal_a[gm]:
        gd -= sal_a[gm]; gm += 1
    return gy, gm, gd


def format_jalali(value, with_time=False, persian_digits=True):
    if not value: return '—'
    if isinstance(value, datetime): d = value.date()
    elif isinstance(value, date): d = value
    else: return str(value)
    jy,jm,jd = gregorian_to_jalali(d.year,d.month,d.day)
    out = f'{jy:04d}/{jm:02d}/{jd:02d}'
    if with_time and isinstance(value, datetime): out += value.strftime(' %H:%M')
    return to_persian_digits(out) if persian_digits else out


def parse_jalali(value):
    if isinstance(value, date): return value
    raw = str(value or '').strip().translate(LATIN_DIGITS).replace('-', '/').replace('.', '/')
    parts = raw.split('/')
    if len(parts) != 3: raise ValueError('تاریخ را به شکل ۱۴۰۵/۰۵/۲۴ وارد کنید.')
    jy,jm,jd = map(int, parts)
    if jy < 1300 or jy > 1600: raise ValueError('سال شمسی معتبر نیست.')
    gy,gm,gd = jalali_to_gregorian(jy,jm,jd)
    return date(gy,gm,gd)
