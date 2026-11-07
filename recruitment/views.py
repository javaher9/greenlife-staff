import json
import math
from datetime import date
from decimal import Decimal
from functools import wraps
from pathlib import PurePath

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, Count, Avg
from django.http import JsonResponse, HttpResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.models import Country, Branch
from .permissions import can_manage, can_approve
from .forms import JobForm, CandidateApplicationForm, ApplicationForm, AdvertisementForm, CandidateForm
from .models import Job, Candidate, Application, Evaluation, Advertisement, Activity, ORGANIZATIONS, JOB_STATUSES, STAGES, SOURCES, AD_STATUSES, TERMINAL_STAGES

User = get_user_model()
ADVANCED_STAGES = {'offer','accepted','started','probation','hired'}


def error(message, status=400, errors=None):
    payload = {'ok':False,'error':message}
    if errors is not None:
        payload['errors'] = errors
    return JsonResponse(payload,status=status)


def api_access(view):
    @wraps(view)
    def wrapped(request,*args,**kwargs):
        if not request.user.is_authenticated:
            return error('برای ادامه وارد حساب خود شوید.',401)
        if not can_manage(request.user):
            return error('دسترسی به استخدام برای این حساب مجاز نیست.',403)
        try:
            response = view(request,*args,**kwargs)
        except (ValidationError, ValueError, TypeError) as exc:
            # Validation messages are deliberately owned by this app, not DB errors.
            message = exc.messages[0] if isinstance(exc,ValidationError) else 'اطلاعات ارسالی معتبر نیست.'
            return error(message)
        except IntegrityError:
            return error('این اطلاعات قبلاً ثبت شده یا هم‌زمان تغییر کرده است؛ صفحه را تازه کنید.',409)
        response['Cache-Control'] = 'private, no-store'
        return response
    return wrapped


def payload(request):
    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValidationError('قالب اطلاعات ارسالی معتبر نیست.')
        if not isinstance(data,dict):
            raise ValidationError('اطلاعات باید به صورت یک شیء ارسال شود.')
        return data
    return request.POST.dict()


def scope(request, queryset, field='country'):
    if getattr(request,'country_scope_code','') == 'ALL':
        return queryset
    country = getattr(request,'country_scope',None)
    # Fail closed if country middleware cannot determine the current workspace.
    return queryset.filter(**{field:country}) if country else queryset.none()


def jobs_for(request):
    return scope(request,Job.objects.select_related('country','branch','owner'))


def apps_for(request):
    return scope(request,Application.objects.select_related('candidate','job','job__country','job__branch','owner').defer('candidate__resume_data','candidate__resume_text'),'job__country')


def countries_for(request):
    countries = Country.objects.filter(is_active=True)
    if getattr(request,'country_scope_code','') == 'ALL':
        return countries
    country = getattr(request,'country_scope',None)
    return countries.filter(pk=country.pk) if country else countries.none()


def staff_for(request):
    from django.conf import settings
    return User.objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(username__in=settings.EXECUTIVE_USERNAMES)
        | Q(profile__is_active=True,profile__role__in=['admin','internal_manager'])
    ).distinct().order_by('first_name','last_name','username')


def name(user):
    return user.get_full_name() or user.username


def iso(value):
    return value.isoformat() if value else None


def event(request, job, kind, text, application=None, changes=None):
    return Activity.objects.create(job=job,application=application,actor=request.user,kind=kind,text=text,changes=changes or {})


def field_snapshot(obj, fields):
    out = {}
    for key in fields:
        value = getattr(obj,key)
        if hasattr(value,'pk'):
            value = value.pk
        if hasattr(value,'isoformat'):
            value = value.isoformat()
        if isinstance(value,Decimal):
            value = str(value)
        out[key] = value
    return out


def changes_between(before,after):
    return {k:{'before':before[k],'after':after[k]} for k in before if before[k] != after[k]}


def job_json(job):
    result = field_snapshot(job,JobForm.Meta.fields)
    result.update(id=job.pk,country_name=job.country.name_local or job.country.name_english,
                  branch_name=job.branch.name if job.branch_id else '',owner_name=name(job.owner),
                  organization_label=job.get_organization_display(),status_label=job.get_status_display(),
                  budget_approved=job.budget_approved,created_at=iso(job.created_at),updated_at=iso(job.updated_at),
                  application_count=getattr(job,'application_count',None))
    if result['application_count'] is None:
        result['application_count'] = job.applications.count()
    return result


def review_visible(request, app, reviews=None):
    if can_approve(request.user):
        return True
    if reviews is not None:
        return any(r.reviewer_id == request.user.pk for r in reviews)
    return app.evaluations.filter(reviewer=request.user).exists()


def app_json(request, app, detail=False):
    reviews = list(app.evaluations.all())
    visible = review_visible(request,app,reviews)
    result = field_snapshot(app,ApplicationForm.Meta.fields)
    result.update(id=app.pk,name=app.candidate.name,phone=app.candidate.phone,job=app.job_id,
                  job_title=app.job.title,organization=app.job.organization,country=app.job.country_id,
                  branch=app.job.branch_id,branch_name=app.job.branch.name if app.job.branch_id else '',
                  source_label=app.get_source_display(),stage_label=app.get_stage_display(),owner_name=name(app.owner),
                  review_required=app.review_required,review_reason=app.review_reason,pending_stage=app.pending_stage,
                  evaluation_count=len(reviews),score=round(sum(float(r.total) for r in reviews)/len(reviews),1) if reviews and visible else None,
                  created_at=iso(app.created_at),updated_at=iso(app.updated_at))
    if not detail:
        return result
    c = app.candidate
    result.update(candidate={'id':c.pk,'name':c.name,'phone':c.phone,'email':c.email,'city':c.city,
                             'resume_text':c.resume_text,'resume_name':c.resume_name,'updated_at':iso(c.updated_at),
                             'resume_url':reverse('recruitment:resume',args=[app.pk]) if c.resume_name else ''},
                  job_detail=job_json(app.job),probation_outcome=app.probation_outcome,
                  approved_by=app.approved_by_id,approved_at=iso(app.approved_at),approved_stage=app.approved_stage,
                  evaluations_hidden=not visible and bool(reviews),evaluations=[],activities=[])
    if visible:
        result['evaluations'] = [dict(id=r.pk,reviewer=r.reviewer_id,reviewer_name=name(r.reviewer),scores=r.scores,
                                     total=float(r.total),evidence=r.evidence,recommendation=r.recommendation,
                                     updated_at=iso(r.updated_at)) for r in reviews]
    for a in app.activities.select_related('actor')[:100]:
        # An evaluator cannot see another evaluator's evidence through audit history.
        if a.kind == 'evaluation' and not visible and a.actor_id != request.user.pk:
            continue
        result['activities'].append(dict(id=a.pk,kind=a.kind,text=a.text,changes=a.changes,
                                         actor_name=name(a.actor),created_at=iso(a.created_at)))
    return result


def ad_json(ad):
    result = field_snapshot(ad,AdvertisementForm.Meta.fields)
    result.update(id=ad.pk,job_title=ad.job.title,source_label=ad.get_source_display(),status_label=ad.get_status_display())
    return result


def form_error(form):
    return error('لطفاً موارد مشخص‌شده را اصلاح کنید.',errors={k:[str(v) for v in values] for k,values in form.errors.items()})


@login_required
def dashboard(request):
    if not can_manage(request.user):
        raise PermissionDenied
    response = render(request,'recruitment/dashboard.html',{'api_root':reverse('recruitment:data'),'can_approve':can_approve(request.user)})
    response['Cache-Control'] = 'private, no-store'
    return response


@require_http_methods(['GET'])
@api_access
def data(request):
    jobs = jobs_for(request).annotate(application_count=Count('applications'))
    apps = apps_for(request)
    all_apps = apps
    q = str(request.GET.get('q','')).strip()[:160]
    if q:
        apps = apps.filter(Q(candidate__name__icontains=q)|Q(candidate__phone__icontains=q)|Q(job__title__icontains=q))
    for key, field in [('job','job_id'),('stage','stage'),('source','source'),('owner','owner_id'),('organization','job__organization'),('branch','job__branch_id')]:
        value = request.GET.get(key)
        if value:
            if key in {'job','owner','branch'} and not value.isdigit():
                return error('فیلتر انتخاب‌شده معتبر نیست.')
            apps = apps.filter(**{field:value})
    now = timezone.now()
    today = timezone.localdate()
    view = request.GET.get('view','')
    if view == 'followups':
        apps = apps.exclude(stage__in=TERMINAL_STAGES-{'talent'})
    elif view == 'onboarding':
        apps = apps.filter(stage__in=['offer','accepted','started','probation','hired'])
    elif view == 'talent':
        apps = apps.filter(stage='talent')
    quick = request.GET.get('quick','')
    if quick == 'today':
        apps = apps.filter(interview_at__date=today).exclude(stage__in=TERMINAL_STAGES)
    elif quick == 'overdue':
        apps = apps.exclude(stage__in=TERMINAL_STAGES-{'talent'}).filter(next_action_at__lt=now)
    elif quick == 'review':
        apps = apps.filter(review_required=True)
    elif quick == 'new':
        apps = apps.filter(stage='new')
    stats = {'active_jobs':jobs.filter(status='open').count(),'new_applications':all_apps.filter(stage='new').count(),
             'overdue':all_apps.exclude(stage__in=TERMINAL_STAGES-{'talent'}).filter(next_action_at__lt=now).count(),
             'interviews_today':all_apps.filter(interview_at__date=today).exclude(stage__in=TERMINAL_STAGES).count(),
             'needs_approval':all_apps.filter(review_required=True).count(),
             'pending_budgets':jobs.filter(budget_approved=False).exclude(status='closed').count(),
             'probation':all_apps.filter(stage='probation').count()}
    choices = {k:[{'value':v,'label':label} for v,label in pairs] for k,pairs in (
        ('organizations',ORGANIZATIONS),('job_statuses',JOB_STATUSES),('stages',STAGES),('sources',SOURCES),('ad_statuses',AD_STATUSES))}
    try:
        page = max(1,int(request.GET.get('page',1)))
    except (TypeError,ValueError):
        return error('شماره صفحه معتبر نیست.')
    limit = 300
    return JsonResponse({'ok':True,'can_approve':can_approve(request.user),'current_user_id':request.user.pk,
        'jobs':[job_json(j) for j in jobs],
        'applications':[app_json(request,a) for a in apps.prefetch_related('evaluations')[(page-1)*limit:page*limit]],
        'applications_total':apps.count(),'page':page,'page_size':limit,
        'ads':[ad_json(a) for a in scope(request,Advertisement.objects.select_related('job'),'job__country')],
        'staff':[{'id':u.pk,'name':name(u)} for u in staff_for(request)],
        'branches':[{'id':b.pk,'name':b.name,'country':b.country_id} for b in scope(request,Branch.objects.filter(is_active=True))],
        'countries':[{'id':c.pk,'name':c.name_local or c.name_english,'code':c.code} for c in countries_for(request)],
        'choices':choices,'stats':stats})


@require_http_methods(['GET','POST'])
@api_access
@transaction.atomic
def job_save(request,pk=None):
    if request.method == 'GET':
        if pk is None:
            return error('شناسه موقعیت را مشخص کنید.',405)
        job = get_object_or_404(jobs_for(request),pk=pk)
        result = job_json(job)
        result['activities'] = [dict(id=a.pk,kind=a.kind,text=a.text,changes=a.changes,actor_name=name(a.actor),created_at=iso(a.created_at))
                                for a in job.activities.filter(application__isnull=True).select_related('actor')[:100]]
        return JsonResponse({'ok':True,'job':result})
    obj = get_object_or_404(jobs_for(request).select_for_update(of=('self',),no_key=True),pk=pk) if pk else None
    values = payload(request)
    action = values.get('action','save')
    if obj and values.get('expected_updated_at') != iso(obj.updated_at):
        return error('این موقعیت هم‌زمان تغییر کرده است؛ اطلاعات جدید را باز کنید و دوباره تصمیم بگیرید.',409)
    if action == 'approve_budget':
        if not can_approve(request.user):
            return error('تأیید بودجه فقط در اختیار مدیریت ارشد است.',403)
        if obj is None or obj.salary_min is None or obj.salary_max is None:
            return error('ابتدا بازه حقوق موقعیت را کامل کنید.')
        obj.budget_approved = True
        obj.budget_approved_by = request.user
        obj.save(update_fields=['budget_approved','budget_approved_by','updated_at'])
        event(request,obj,'budget_approved','بازه حقوق موقعیت تأیید شد.')
        return JsonResponse({'ok':True,'job':job_json(obj)})
    if action != 'save':
        return error('عملیات درخواست‌شده معتبر نیست.')
    before = field_snapshot(obj,JobForm.Meta.fields) if obj else None
    merged = dict(before or {'organization':'clinic','headcount':1,'status':'draft'})
    merged.update(values)
    form = JobForm(merged,instance=obj,countries=countries_for(request),branches=scope(request,Branch.objects.filter(is_active=True)),staff=staff_for(request))
    if not form.is_valid():
        return form_error(form)
    if obj and not can_approve(request.user) and form.cleaned_data['requires_executive_approval'] != before['requires_executive_approval']:
        return error('تغییر الزام تأیید نهایی فقط در اختیار مدیریت ارشد است.',403)
    obj = form.save(commit=False)
    if not obj.pk:
        obj.created_by = request.user
    changed = changes_between(before,field_snapshot(obj,JobForm.Meta.fields)) if before else {}
    reset_budget = bool(before and any(k in changed for k in ['salary_min','salary_max','benefits','shift','headcount','title','description','requirements','location','branch']))
    if reset_budget:
        obj.budget_approved = False
        obj.budget_approved_by = None
    obj.save()
    if reset_budget or 'requires_executive_approval' in changed:
        for application in obj.applications.exclude(stage__in=TERMINAL_STAGES).filter(Q(approved_by__isnull=False)|Q(stage__in=ADVANCED_STAGES)).select_for_update():
            application.approved_by = None
            application.approved_at = None
            application.approved_stage = ''
            application.review_required = True
            application.review_reason = 'شرایط موقعیت تغییر کرده و نیازمند تأیید مجدد است.'
            application.save(update_fields=['approved_by','approved_at','approved_stage','review_required','review_reason','updated_at'])
            event(request,obj,'approval_invalidated',application.review_reason,application)
    event(request,obj,'job_updated' if before else 'job_created','موقعیت شغلی ویرایش شد.' if before else 'موقعیت شغلی ایجاد شد.',changes=changed)
    return JsonResponse({'ok':True,'job':job_json(obj)})


@require_http_methods(['POST'])
@api_access
@transaction.atomic
def application_create(request):
    values = payload(request)
    values.setdefault('source','manual')
    form = CandidateApplicationForm(values,request.FILES,jobs=jobs_for(request),staff=staff_for(request))
    if not form.is_valid():
        return form_error(form)
    d = form.cleaned_data
    job = jobs_for(request).select_for_update(of=('self',),no_key=True).get(pk=d['job'].pk)
    if job.status == 'closed':
        return error('این موقعیت بسته شده است؛ ابتدا آن را باز کنید.')
    candidate, created = Candidate.objects.get_or_create(country=job.country,phone=d['phone'],defaults={
        'name':d['name'],'email':d['email'],'city':d['city'],'resume_text':d['resume_text']})
    if not created and ' '.join(candidate.name.split()) != ' '.join(d['name'].split()):
        return error('این شماره قبلاً با نام دیگری ثبت شده است؛ نام و شماره را بررسی کنید.')
    if Application.objects.filter(candidate=candidate,job=job).exists():
        return error('این متقاضی برای این موقعیت قبلاً ثبت شده است.')
    if created and d.get('resume'):
        upload = d['resume']
        candidate.resume_data = upload.read()
        candidate.resume_name = PurePath(upload.name).name[:200]
        candidate.save(update_fields=['resume_data','resume_name'])
    app = Application.objects.create(candidate=candidate,job=job,owner=d['owner'],source=d.get('source') or 'manual',
        source_detail=d['source_detail'],next_action=d['next_action'],next_action_at=d['next_action_at'],
        requested_salary=d['requested_salary'],created_by=request.user)
    event(request,job,'application_created','درخواست همکاری ثبت شد.',app)
    if d['notes']:
        event(request,job,'note',d['notes'],app)
    return JsonResponse({'ok':True,'application':app_json(request,app,True),'candidate_reused':not created})


def _review_reason(app, target_stage, salary_changed=False):
    advanced_approved = bool(app.approved_by_id and app.approved_stage in ADVANCED_STAGES)
    if target_stage in ADVANCED_STAGES:
        out_of_range = app.offered_salary is not None and (app.job.salary_max is None or
            app.offered_salary > app.job.salary_max or app.offered_salary < (app.job.salary_min or 0))
        if not advanced_approved and out_of_range:
            return 'حقوق پیشنهادی خارج از بازه مصوب است.'
        if not advanced_approved and app.job.requires_executive_approval:
            return 'این موقعیت به تأیید نهایی مدیریت ارشد نیاز دارد.'
    if target_stage == 'rejected' and not (app.approved_by_id and app.approved_stage == 'rejected'):
        average = app.evaluations.aggregate(value=Avg('total'))['value']
        if average is not None and average >= 75:
            return 'رد متقاضی دارای ارزیابی قوی نیازمند بازبینی مدیریت است.'
    return ''


@require_http_methods(['GET','POST'])
@api_access
def application_detail(request,pk):
    if request.method == 'GET':
        app = get_object_or_404(apps_for(request).prefetch_related('evaluations__reviewer'),pk=pk)
        return JsonResponse({'ok':True,'application':app_json(request,app,True)})
    with transaction.atomic():
        job_id = apps_for(request).filter(pk=pk).values_list('job_id',flat=True).first()
        if job_id is None:
            raise Http404
        get_object_or_404(jobs_for(request).select_for_update(of=('self',),no_key=True),pk=job_id)
        app = get_object_or_404(apps_for(request).select_for_update(of=('self',),no_key=True),pk=pk)
        values = payload(request)
        action = values.get('action','update')
        if action in {'update','approve','probation'} and values.get('expected_updated_at') != iso(app.updated_at):
            return error('این پرونده هم‌زمان تغییر کرده است؛ پرونده را دوباره باز کنید تا اطلاعات جدید را ببینید.',409)
        if action == 'candidate_update':
            candidate = Candidate.objects.select_for_update(no_key=True).get(pk=app.candidate_id)
            if values.get('expected_candidate_updated_at') != iso(candidate.updated_at):
                return error('مشخصات متقاضی هم‌زمان تغییر کرده است؛ پرونده را دوباره باز کنید.',409)
            if 'phone' in values and values['phone'] != candidate.phone:
                return error('تغییر شماره مشترک متقاضی از این فرم مجاز نیست.')
            before = field_snapshot(candidate,CandidateForm.Meta.fields + ['resume_name'])
            merged = {key:before[key] for key in CandidateForm.Meta.fields}
            merged.update(values)
            form = CandidateForm(merged,request.FILES,instance=candidate)
            if not form.is_valid():
                return form_error(form)
            candidate = form.save(commit=False)
            upload = form.cleaned_data.get('resume')
            if upload:
                candidate.resume_data = upload.read()
                candidate.resume_name = PurePath(upload.name).name[:200]
            candidate.save()
            changes = changes_between(before,field_snapshot(candidate,CandidateForm.Meta.fields + ['resume_name']))
            if upload:
                changes['resume_replaced'] = True
            for related in candidate.applications.select_related('job'):
                event(request,related.job,'candidate_updated','مشخصات و رزومه مشترک متقاضی به‌روزرسانی شد.',related,changes)
        elif action == 'note':
            text = str(values.get('text','')).strip()
            if not text or len(text)>5000:
                return error('یادداشت باید بین ۱ تا ۵۰۰۰ نویسه باشد.')
            event(request,app.job,'note',text,app)
        elif action == 'evaluate':
            scores = values.get('scores')
            if isinstance(scores,str):
                try:
                    scores = json.loads(scores)
                except json.JSONDecodeError:
                    return error('امتیاز معیارها معتبر نیست.')
            criteria = app.job.criteria
            if not isinstance(scores,list) or len(scores) != len(criteria):
                return error('برای تمام معیارهای موقعیت امتیاز وارد کنید.')
            if any(isinstance(s,bool) or not isinstance(s,(int,float)) or not math.isfinite(s) or not 0 <= s <= 100 for s in scores):
                return error('امتیاز هر معیار باید عددی بین صفر و صد باشد.')
            evidence = str(values.get('evidence','')).strip()
            recommendation = values.get('recommendation','review')
            if not evidence or len(evidence)>5000 or recommendation not in {'advance','review','decline'}:
                return error('شواهد ارزیابی و پیشنهاد نهایی معتبر وارد کنید.')
            snapshot = [{**c,'score':s} for c,s in zip(criteria,scores)]
            total = round(sum(c['weight']*s/100 for c,s in zip(criteria,scores)),2)
            old = app.evaluations.filter(reviewer=request.user).first()
            before = {'scores':old.scores,'total':str(old.total),'evidence':old.evidence,'recommendation':old.recommendation} if old else None
            review, _ = Evaluation.objects.update_or_create(application=app,reviewer=request.user,defaults={
                'scores':snapshot,'total':Decimal(str(total)),'evidence':evidence,'recommendation':recommendation})
            event(request,app.job,'evaluation','ارزیابی مستقل ثبت شد.',app,{'before':before,'after':{'scores':snapshot,'total':total,'evidence':evidence,'recommendation':recommendation}})
            # Independent disagreement is surfaced without making a hiring decision.
            totals = [float(x) for x in app.evaluations.values_list('total',flat=True)]
            disagreement = len(totals) >= 2 and max(totals)-min(totals) >= 25
            prior_approval = bool(app.approved_by_id)
            app.approved_by = None
            app.approved_at = None
            app.approved_stage = ''
            if disagreement or prior_approval:
                app.review_required = True
                app.review_reason = ('اختلاف قابل توجه ارزیابی‌های مستقل نیازمند بازبینی مدیریت است.' if disagreement
                                     else 'شواهد ارزیابی پس از تأیید تغییر کرده و نیازمند بازبینی است.')
                event(request,app.job,'review_requested',app.review_reason,app)
            app.save(update_fields=['approved_by','approved_at','approved_stage','review_required','review_reason','updated_at'])
        elif action == 'approve':
            if not can_approve(request.user):
                return error('تأیید نهایی فقط در اختیار مدیریت ارشد است.',403)
            text = str(values.get('text','')).strip()
            decision = values.get('decision','approve')
            if not text or len(text)>5000 or decision not in {'approve','return'}:
                return error('نتیجه و توضیح تصمیم را وارد کنید.')
            if not app.review_required:
                return error('این پرونده درخواست تأیید معلق ندارد.')
            if decision == 'approve':
                target = app.pending_stage or app.stage
                approval_values = field_snapshot(app,ApplicationForm.Meta.fields)
                approval_values['stage'] = target
                approval_form = ApplicationForm(approval_values,instance=app,staff=staff_for(request))
                if not approval_form.is_valid():
                    return form_error(approval_form)
                if target in ADVANCED_STAGES and not app.job.budget_approved:
                    return error('ابتدا بودجه موقعیت شغلی را تأیید کنید.')
                app.approved_by = request.user
                app.approved_at = timezone.now()
                app.approved_stage = target
                if app.pending_stage:
                    app.stage = app.pending_stage
                app.review_required = False
                app.review_reason = ''
                app.pending_stage = ''
            else:
                app.stage = 'decision'
                app.review_required = False
                app.review_reason = ''
                app.pending_stage = ''
                app.approved_by = None
                app.approved_at = None
                app.approved_stage = ''
            app.save()
            event(request,app.job,'approval' if decision=='approve' else 'returned',text,app,{'decision':decision,'stage':app.stage})
        elif action == 'probation':
            if app.stage not in {'started','probation','hired'}:
                return error('ثبت نتیجه دوره آزمایشی پس از شروع کار امکان‌پذیر است.')
            outcome = str(values.get('probation_outcome','')).strip()
            if not outcome or len(outcome)>5000:
                return error('نتیجه دوره آزمایشی را ثبت کنید (حداکثر ۵۰۰۰ نویسه).')
            before = field_snapshot(app,['probation_outcome','probation_review_at','start_date'])
            app.probation_outcome = outcome
            for field in ['probation_review_at','start_date']:
                if field in values:
                    value = values[field]
                    try:
                        setattr(app,field,date.fromisoformat(str(value)) if value else None)
                    except ValueError:
                        return error('تاریخ واردشده معتبر نیست.')
            if not app.start_date:
                return error('تاریخ شروع کار را نمی‌توان خالی کرد.')
            app.save()
            event(request,app.job,'probation','نتیجه ارزیابی دوره آزمایشی ثبت شد.',app,changes_between(before,field_snapshot(app,['probation_outcome','probation_review_at','start_date'])))
        elif action == 'update':
            before = field_snapshot(app,ApplicationForm.Meta.fields)
            merged = dict(before)
            merged.update(values)
            form = ApplicationForm(merged,instance=app,staff=staff_for(request))
            if not form.is_valid():
                return form_error(form)
            app = form.save(commit=False)
            target = app.stage
            salary_changed = before['offered_salary'] != app.offered_salary
            decision_changed = before['decision_reason'] != app.decision_reason
            if salary_changed or decision_changed or (target == 'rejected' and target != before['stage']) or (before['stage'] in TERMINAL_STAGES and target != before['stage']):
                app.approved_by = None
                app.approved_at = None
                app.approved_stage = ''
            if target in ADVANCED_STAGES and not app.job.budget_approved:
                return error('پیش از پیشنهاد همکاری، بودجه موقعیت باید تأیید شود.')
            if app.review_required and target not in ADVANCED_STAGES and target not in {'decision','rejected'}:
                # Reworking an active application cancels only the proposed transition,
                # not the independent-review obligation. Otherwise a manager could
                # erase disagreement through offer -> screening -> offer.
                app.pending_stage = ''
                app.approved_by = None
                app.approved_at = None
                app.approved_stage = ''
                if target in {'withdrawn','talent','salary_declined'}:
                    app.review_required = False
                    app.review_reason = ''
                    event(request,app.job,'approval_cancelled','با پایان رسیدگی جاری، درخواست تأیید قبلی لغو شد.',app)
                else:
                    event(request,app.job,'review_retained','مرحله پیشنهادی قبلی لغو شد؛ پرونده همچنان نیازمند بازبینی مدیریت است.',app)
            reason = _review_reason(app,target,salary_changed)
            if reason:
                app.pending_stage = target
                app.stage = 'decision'
                app.review_required = True
                app.review_reason = reason
                # A pending decision is active work even if intended final stage was terminal.
                if not app.next_action.strip() or not app.next_action_at:
                    return error('برای پرونده نیازمند تأیید، اقدام بعدی و موعد آن را مشخص کنید.')
            elif app.review_required:
                # Existing pending approval cannot be silently cleared by editing unrelated fields.
                if target in ADVANCED_STAGES or target in {'rejected','hired'}:
                    app.pending_stage = target
                    app.stage = 'decision'
            app.save()
            event(request,app.job,'application_updated','پرونده و مرحله رسیدگی ویرایش شد.',app,
                  changes_between(before,field_snapshot(app,ApplicationForm.Meta.fields)))
        else:
            return error('عملیات درخواست‌شده معتبر نیست.')
        app = apps_for(request).prefetch_related('evaluations__reviewer').get(pk=app.pk)
        return JsonResponse({'ok':True,'application':app_json(request,app,True)})


@require_http_methods(['POST'])
@api_access
@transaction.atomic
def ad_save(request,pk=None):
    obj = get_object_or_404(scope(request,Advertisement.objects.select_related('job').select_for_update(of=('self',),no_key=True),'job__country'),pk=pk) if pk else None
    values = payload(request)
    before = field_snapshot(obj,AdvertisementForm.Meta.fields) if obj else None
    merged = dict(before or {'source':'divar','status':'draft'})
    merged.update(values)
    form = AdvertisementForm(merged,instance=obj,jobs=jobs_for(request))
    if not form.is_valid():
        return form_error(form)
    obj = form.save(commit=False)
    if not obj.pk:
        obj.created_by = request.user
    obj.save()
    event(request,obj.job,'ad_updated' if before else 'ad_created','اطلاعات آگهی ثبت شد.',changes={
        'ad_id':obj.pk,'changes':changes_between(before,field_snapshot(obj,AdvertisementForm.Meta.fields)) if before else {}})
    return JsonResponse({'ok':True,'ad':ad_json(obj)})


@require_http_methods(['GET'])
@api_access
def resume(request,pk):
    app = get_object_or_404(apps_for(request),pk=pk)
    candidate = Candidate.objects.only('resume_data','resume_name').get(pk=app.candidate_id)
    if not candidate.resume_data:
        raise Http404
    response = HttpResponse(bytes(candidate.resume_data),content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="candidate-resume.pdf"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
