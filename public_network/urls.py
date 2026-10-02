from django.urls import path

from . import views

app_name = 'public_network'

urlpatterns = [
    path('tr/network/', views.turkey_signup, name='turkey_signup'),
    path('tr/network/terms/', views.turkey_terms, name='turkey_terms'),
    path('tr/network/login/', views.turkey_login, name='turkey_login'),
    path('tr/network/logout/', views.turkey_logout, name='turkey_logout'),
    path('tr/network/dashboard/', views.turkey_dashboard, name='turkey_dashboard'),
    path('tr/network/lead/new/', views.turkey_lead_create, name='turkey_lead_create'),
    path('tr/network/lead/<str:code>/', views.turkey_public_lead, name='turkey_public_lead'),
    path('tr/network/lead/<str:code>/qr/', views.turkey_public_lead_qr, name='turkey_public_lead_qr'),
    path('tr/network/invite/<str:code>/qr/', views.turkey_invite_qr, name='turkey_invite_qr'),
    path('tr/network/<str:code>/', views.turkey_signup, name='turkey_signup_with_code'),
    path('join/greenlife/', views.signup, name='signup'),
    path('join/greenlife/terms/', views.terms, name='terms'),
    path('join/greenlife/login/', views.member_login, name='login'),
    path('join/greenlife/logout/', views.member_logout, name='logout'),
    path('join/greenlife/<str:code>/', views.signup, name='signup_with_code'),
    path('public-network/', views.dashboard, name='dashboard'),
    path('public-network/invite/<str:code>/qr/', views.invite_qr, name='invite_qr'),
    path('referrals/public-network/', views.management, name='management'),
]
