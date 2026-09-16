from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from core import call_center_views, consultant_sales_views, instagram_views, lead_ingest_views, lead_management_views

urlpatterns=[
    path('admin/',admin.site.urls),
    path('api/integrations/leads/',lead_ingest_views.ingest_lead,name='lead_ingest'),
    path('instagram/',instagram_views.instagram_lead,name='instagram_lead'),
    path('telegram/',instagram_views.telegram_lead,name='telegram_lead'),
    path('instagram/manual/',instagram_views.instagram_manual_lead,name='instagram_manual_lead'),
    path('call-center/leads/<int:pk>/call-started/',call_center_views.mark_call_started,name='call_center_mark_call_started'),
    path('lead-management/',lead_management_views.lead_management_dashboard,name='lead_management_dashboard'),
    path('consultant/sales/',consultant_sales_views.consultant_sales_outcomes,name='consultant_sales_outcomes'),
    path('',include('public_network.urls')),
    path('',include('core.urls')),
]
if settings.DEBUG: urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
