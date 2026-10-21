from django.urls import path
from . import views
urlpatterns = [
    path('intake/appointments/<int:pk>/send/', views.send_link, name='intake_send_link'),
    path('intake/form/<str:token>/', views.intake_form, name='intake_public_form'),
]
