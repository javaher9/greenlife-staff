from django.urls import path

from . import digital_referral_views


urlpatterns = [
    path('join/greenlife/', digital_referral_views.digital_signup, name='digital_referral_signup'),
    path('digital-network/', digital_referral_views.digital_referral_portal, name='digital_referral_portal'),
    path('referrals/digital/', digital_referral_views.digital_referral_dashboard, name='digital_referral_dashboard'),
]
