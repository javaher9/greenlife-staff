from django.urls import path

from . import views

app_name = 'public_network'

urlpatterns = [
    path('join/greenlife/', views.signup, name='signup'),
    path('join/greenlife/login/', views.member_login, name='login'),
    path('join/greenlife/logout/', views.member_logout, name='logout'),
    path('join/greenlife/<str:code>/', views.signup, name='signup_with_code'),
    path('public-network/', views.dashboard, name='dashboard'),
    path('public-network/invite/<str:code>/qr/', views.invite_qr, name='invite_qr'),
    path('referrals/public-network/', views.management, name='management'),
]
