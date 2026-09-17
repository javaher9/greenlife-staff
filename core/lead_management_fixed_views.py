from .lead_management_views import lead_management_dashboard as _dashboard


def lead_management_dashboard(request):
    response = _dashboard(request)
    if getattr(response, 'status_code', 500) != 200 or not hasattr(response, 'content'):
        return response
    try:
        html = response.content.decode(response.charset or 'utf-8')
        admin = bool(request.user.is_superuser or (getattr(request.user, 'profile', None) and request.user.profile.role == 'admin'))
        extra = '''<style id="lead-row-dark-fix">
body.gl-premium-dark .lead-page table tr,body.gl-premium-dark .lead-page table tr:hover,body.gl-premium-dark .lead-page table tr:focus,body.gl-premium-dark .lead-page table tr:focus-within,body.gl-premium-dark .lead-page table tr:active,body.gl-premium-dark .lead-page table td,body.gl-premium-dark .lead-page table td:hover,body.gl-premium-dark .lead-page table td:focus{background-color:#10151e!important;background-image:none!important;color:#f8fafc!important}
body.gl-premium-dark .lead-page table thead tr,body.gl-premium-dark .lead-page table thead tr:hover,body.gl-premium-dark .lead-page table th{background:linear-gradient(90deg,#173c32 0%,#252243 52%,#172d3d 100%)!important;color:#e5edf6!important}
body.gl-premium-dark .lead-page table a:focus,body.gl-premium-dark .lead-page table button:focus{outline:2px solid #7c5cff!important;outline-offset:2px}.lead-admin-actions{display:inline-flex;gap:5px;margin-inline-start:6px}.lead-admin-actions a{padding:5px 8px;border-radius:8px;text-decoration:none!important;font-size:9px;font-weight:900}.lead-admin-edit{background:#173b34!important;color:#77e4c1!important;border:1px solid #2f6f61}.lead-admin-delete{background:#3a1b24!important;color:#ff9aaa!important;border:1px solid #713244}
</style>'''
        if admin:
            extra += '''<script id="lead-admin-controls">document.addEventListener('DOMContentLoaded',function(){document.querySelectorAll('.lead-page a[href*="/referrals/leads/"][href$="/manage/"]').forEach(function(a){var m=a.getAttribute('href').match(/\/referrals\/leads\/(\d+)\/manage\//);if(!m)return;var host=a.parentElement;if(!host||host.querySelector('.lead-admin-actions'))return;var box=document.createElement('span');box.className='lead-admin-actions';box.innerHTML='<a class="lead-admin-edit" href="/lead-management/leads/'+m[1]+'/edit/">ویرایش</a><a class="lead-admin-delete" href="/lead-management/leads/'+m[1]+'/delete/">حذف</a>';host.appendChild(box);});});</script>'''
        html = html.replace('</body>', extra + '</body>')
        response.content = html.encode(response.charset or 'utf-8')
        response['Content-Length'] = str(len(response.content))
    except Exception:
        pass
    return response
