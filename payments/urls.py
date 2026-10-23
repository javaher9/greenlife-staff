from django.urls import path
from . import views
urlpatterns=[
 path('',views.workspace,name='payments_workspace'),
 path('executive/new/',views.executive_quick_payment,name='payments_executive_quick'),
 path('review/<int:pk>/',views.review,name='payments_review'),
 path('complete/<int:pk>/',views.mark_paid,name='payments_complete'),
 path('clarification/<int:pk>/answer/',views.answer_clarification,name='payments_clarification_answer'),
 path('receipt/<int:pk>/',views.receipt,name='payments_receipt'),
 path('petty-receipt/<int:pk>/',views.petty_receipt,name='payments_petty_receipt'),
 path('admin/',views.admin_dashboard,name='payments_admin'),
 path('expenses/',views.expenses_dashboard,name='payments_expenses'),
 path('accounting/',views.accounting_hub,name='payments_accounting'),
]
