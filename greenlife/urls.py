from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from core import instagram_views

urlpatterns=[
    path('admin/',admin.site.urls),
    path('instagram/',instagram_views.instagram_lead,name='instagram_lead'),
    path('',include('public_network.urls')),
    path('',include('core.urls')),
]
if settings.DEBUG: urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)