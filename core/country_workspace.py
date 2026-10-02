from django.conf import settings

from .models import Country


COUNTRY_SCOPE_SESSION_KEY = 'greenlife_country_scope'
GLOBAL_COUNTRY_ROLES = {'admin', 'internal_manager'}


def can_switch_country(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    username=(getattr(user,'username','') or '').lower()
    profile=getattr(user,'profile',None)
    return bool(
        getattr(user,'is_superuser',False)
        or username in settings.EXECUTIVE_USERNAMES
        or getattr(profile,'role','') in GLOBAL_COUNTRY_ROLES
    )


def country_for_user(user):
    if not user or not getattr(user,'is_authenticated',False):
        return None

    member=getattr(user,'public_network_member',None)
    member_country=getattr(member,'country',None) if member else None
    if member_country:
        return member_country

    profile=getattr(user,'profile',None)
    if profile:
        if getattr(profile,'country_id',None):
            return profile.country
        branch=getattr(profile,'branch',None)
        if branch and getattr(branch,'country_id',None):
            return branch.country

    return Country.objects.filter(code='IR',is_active=True).first()


def resolve_country_workspace(request):
    user=getattr(request,'user',None)
    if not user or not getattr(user,'is_authenticated',False):
        return {
            'country':None,
            'code':'',
            'can_switch':False,
            'countries':Country.objects.none(),
        }

    switchable=can_switch_country(user)
    countries=Country.objects.filter(is_active=True).order_by('sort_order','name_english','code')
    own_country=country_for_user(user)

    if not switchable:
        return {
            'country':own_country,
            'code':getattr(own_country,'code',''),
            'can_switch':False,
            'countries':countries,
        }

    selected=(request.session.get(COUNTRY_SCOPE_SESSION_KEY) or '').upper()
    if selected=='ALL':
        return {'country':None,'code':'ALL','can_switch':True,'countries':countries}

    country=countries.filter(code=selected).first() if selected else None
    if country is None:
        country=own_country or countries.filter(code='IR').first() or countries.first()
        if country:
            request.session[COUNTRY_SCOPE_SESSION_KEY]=country.code

    return {
        'country':country,
        'code':getattr(country,'code',''),
        'can_switch':True,
        'countries':countries,
    }


def scoped_queryset(request, queryset, field='country'):
    """Apply the request's country scope without changing legacy query semantics."""
    code=getattr(request,'country_scope_code','')
    if code=='ALL':
        return queryset
    country=getattr(request,'country_scope',None)
    if not country:
        return queryset
    return queryset.filter(**{field:country})


class CountryWorkspaceMiddleware:
    """Resolve one safe country scope per request after authentication."""

    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        user=getattr(request,'user',None)
        if not user or not getattr(user,'is_authenticated',False):
            request.country_scope=None
            request.country_scope_code=''
            request.country_scope_can_switch=False
            request.country_scope_countries=Country.objects.none()
            return self.get_response(request)

        workspace=resolve_country_workspace(request)
        request.country_scope=workspace['country']
        request.country_scope_code=workspace['code']
        request.country_scope_can_switch=workspace['can_switch']
        request.country_scope_countries=workspace['countries']
        return self.get_response(request)
