"""Private meal monitoring; clinical roles only, scoped to assigned branch."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from .models import PatientProfile
from django.shortcuts import render
from django.views.decorators.http import require_GET
from .me_diet_models import MeMealReport


@login_required
@require_GET
def monitor(request):
    profile=getattr(request.user,'profile',None)
    role=getattr(profile,'role',None)
    if role not in {'admin','internal_manager','doctor','consultant','manager'}:
        raise PermissionDenied()
    qs=MeMealReport.objects.select_related('member','patient','program').order_by('-day','-updated_at')
    if role not in {'admin','internal_manager'}:
        qs=qs.filter(Q(patient__home_branch_id=profile.branch_id) | Q(patient__isnull=True,member__phone__in=PatientProfile.objects.filter(home_branch_id=profile.branch_id).values('phone'))) if profile.branch_id else qs.none()
    q=request.GET.get('q','').strip()[:100]
    if q:qs=qs.filter(member__full_name__icontains=q)
    page=Paginator(qs,25).get_page(request.GET.get('page'))
    response=render(request,'core/me_meal_monitor.html',{'page':page,'q':q,'executive':role in {'admin','internal_manager','manager'}})
    response['Cache-Control']='private, no-store'
    return response
