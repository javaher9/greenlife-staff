from django.urls import path
from . import views

app_name = 'recruitment'
urlpatterns = [
    path('',views.dashboard,name='dashboard'),
    path('api/',views.data,name='data'),
    path('api/jobs/',views.job_save,name='job_create'),
    path('api/jobs/<int:pk>/',views.job_save,name='job_update'),
    path('api/applications/',views.application_create,name='application_create'),
    path('api/applications/<int:pk>/',views.application_detail,name='application_detail'),
    path('api/applications/<int:pk>/resume/',views.resume,name='resume'),
    path('api/ads/',views.ad_save,name='ad_create'),
    path('api/ads/<int:pk>/',views.ad_save,name='ad_update'),
]
