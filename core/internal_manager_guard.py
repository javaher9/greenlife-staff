"""Close legacy referral management bypasses for the supervisory role."""
from django.http import HttpResponseForbidden


class InternalManagerGuard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(getattr(getattr(request,'user',None),'profile',None),'role',None) == 'internal_manager':
            response['Cache-Control'] = 'private, no-store'
        return response

    def process_view(self, request, view, args, kwargs):
        if getattr(getattr(request.user,'profile',None),'role',None) != 'internal_manager':
            return None
        module = view.__module__
        # These old modules expose phone numbers, commissions, exports or writes.
        # The existing compact archive and monthly staff report remain available.
        if module in {'core.referral_views','core.referral_admin_views','core.referral_tree_views','core.lead_management_views','core.lead_action_views','core.lead_command_views','core.patient_360_views','core.lead_freshness_views'}:
            return HttpResponseForbidden('برای نظارت از صفحه لیدهای فشرده یا گزارش ماهانه پرسنل استفاده کنید.')
