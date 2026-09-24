from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from core import call_center_views, consultant_sales_views, instagram_views, lead_ingest_views, lead_action_views, lead_admin_views, lead_management_fixed_views, website_integration_views

urlpatterns=[
    path('admin/',admin.site.urls),
    path('api/integrations/leads/',lead_ingest_views.ingest_lead,name='lead_ingest'),
    path('settings/website-leads/',website_integration_views.website_lead_settings,name='website_lead_settings'),
    path('instagram/',instagram_views.instagram_lead,name='instagram_lead'),
    path('telegram/',instagram_views.telegram_lead,name='telegram_lead'),
    path('instagram/manual/',instagram_views.instagram_manual_lead,name='instagram_manual_lead'),
    path('call-center/alerts/check/',call_center_views.check_lead_delay_alerts,name='call_center_check_lead_delay_alerts'),path('call-center/leads/<int:pk>/call-started/',call_center_views.mark_call_started,name='call_center_mark_call_started'),
    path('call-center/leads/<int:pk>/result/',call_center_views.save_call_result,name='call_center_save_call_result'),
    path('lead-management/',lead_management_fixed_views.lead_management_dashboard,name='lead_management_dashboard'),
    path('lead-management/leads/<int:pk>/edit/',lead_admin_views.admin_lead_edit,name='admin_lead_edit'),
    path('lead-management/leads/<int:pk>/delete/',lead_admin_views.admin_lead_delete,name='admin_lead_delete'),
    # Lead Hub managers must be able to act on every lead, including leads whose
    # referrer is a technical/inactive integration source. Keep the historical
    # URL so existing dashboard links continue to work, but resolve it here
    # before the referral-network-scoped route in core.urls.
    path('referrals/leads/<int:pk>/manage/',lead_action_views.management_lead_follow_up,name='management_lead_follow_up'),
    path('consultant/sales/',consultant_sales_views.consultant_sales_outcomes,name='consultant_sales_outcomes'),
    path('',include('public_network.urls')),
    path('',include('core.urls')),
]
if settings.DEBUG: urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
