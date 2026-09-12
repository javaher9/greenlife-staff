from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from core import instagram_views, lead_ingest_views, lead_management_views

urlpatterns=[
    path('admin/',admin.site.urls),
    path('api/integrations/leads/',lead_ingest_views.ingest_lead,name='lead_ingest'),
    path('instagram/',instagram_views.instagram_lead,name='instagram_lead'),
    path('lead-management/',lead_management_views.lead_management_dashboard,name='lead_management_dashboard'),
    path('',include('public_network.urls')),
    path('',include('core.urls')),
]
if settings.DEBUG: urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
