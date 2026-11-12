from django.urls import path
from . import views
urlpatterns = [
    path('schools/', views.dashboard, name='schools_dashboard'),
    path('schools/new/', views.program_edit, name='schools_new'),
    path('schools/<int:pk>/', views.detail, name='schools_detail'),
    path('schools/<int:pk>/edit/', views.program_edit, name='schools_edit'),
    path('schools/<int:pk>/card/', views.invite_card, name='schools_card'),
    path('schools/<int:pk>/qr.png', views.qr, name='schools_qr'),
    path('schools/families/<int:pk>/', views.coordinate, name='schools_coordinate'),
    path('schools/clinical/', views.clinical, name='schools_clinical'),
    path('schools/clinical/<int:pk>/', views.clinical, name='schools_clinical_child'),
    path('customer/schools/<uuid:token>/', views.join, name='schools_join'),
    path('customer/family/', views.family, name='schools_family'),
    path('customer/family/<int:pk>/child/', views.child_add, name='schools_child_add'),
    path('customer/manifest.webmanifest', views.manifest, name='schools_manifest'),
    path('customer/sw.js', views.service_worker, name='schools_service_worker'),
]
