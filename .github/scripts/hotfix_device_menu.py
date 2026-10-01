from pathlib import Path

path = Path("/app/core/templates/core/base.html")
text = path.read_text(encoding="utf-8")

if "device_capacity_settings" not in text:
    lines = text.splitlines()
    out = []
    inserted = False
    link = "        <a href=\"{% url 'device_capacity_settings' %}\" class=\"{% if request.resolver_match.url_name == 'device_capacity_settings' %}is-active{% endif %}\"><span class=\"nav-ico\">▣</span><span>دستگاه‌ها و ظرفیت نوبت‌دهی</span></a>"
    for line in lines:
        out.append(line)
        if (not inserted and "website_lead_settings" in line and "اتصال لید وب‌سایت" in line):
            out.append(link)
            inserted = True
    if not inserted:
        raise SystemExit("settings submenu insertion point not found")
    text = "\n".join(out) + "\n"

needle = "request.resolver_match.url_name == 'shift_today_bulk'"
replacement = "request.resolver_match.url_name == 'device_capacity_settings' or " + needle
if "url_name == 'device_capacity_settings' or request.resolver_match.url_name == 'shift_today_bulk'" not in text:
    text = text.replace(needle, replacement, 1)

path.write_text(text, encoding="utf-8")
print("patched", path)
