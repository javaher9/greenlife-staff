from django.urls import path
from . import views, preview
urlpatterns = [
    path('intake/preview/weight/', preview.weight_preview, name='intake_weight_preview'),
    path('intake/appointments/<int:pk>/send/', views.send_link, name='intake_send_link'),
    path('intake/form/<str:token>/', views.intake_form, name='intake_public_form'),
]
