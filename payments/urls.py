from django.urls import path
from . import views
urlpatterns=[
 path('',views.workspace,name='payments_workspace'),
 path('review/<int:pk>/',views.review,name='payments_review'),
 path('complete/<int:pk>/',views.mark_paid,name='payments_complete'),
 path('admin/',views.admin_dashboard,name='payments_admin'),
]
