"""Synthetic local/CI fixture only. Refuses production settings."""
from django.conf import settings
assert settings.DEBUG and settings.DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3'
from datetime import date
from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.utils import timezone
from core.models import Branch, CustomerPortalMember
from schools.models import Organization, SchoolProgram, FamilyEnrollment, Child, GrowthRecord
import json
b,_=Branch.objects.get_or_create(name='نیاوران')
users={}
for name, role, enabled in [('school-demo-owner','admin',False),('school-demo-moradi','consultant',True),('school-demo-doctor','doctor',False)]:
 u,_=User.objects.get_or_create(username=name)
 u.is_active=True
 u.set_unusable_password();u.save()
 p=u.profile;p.role=role;p.branch=b;p.can_manage_schools=enabled;p.save()
 s=SessionStore();s['_auth_user_id']=str(u.pk);s['_auth_user_backend']='django.contrib.auth.backends.ModelBackend';s['_auth_user_hash']=u.get_session_auth_hash();s.save();users[role]=s.session_key
org,_=Organization.objects.get_or_create(name='دبستان نمونهٔ نیاوران',branch=b,defaults={'created_by':u})
p,_=SchoolProgram.objects.get_or_create(organization=org,defaults={'coordinator':u,'state':'open','capacity':50,'terms':'ارزیابی رشد فرزند، توضیح پزشک و پیگیری خانواده. شرایط این صفحه آزمایشی است.'})
m,_=CustomerPortalMember.objects.get_or_create(phone='09120000000',defaults={'referral_code':'DEMO-SCHOOLS','full_name':'والد نمونه'})
e,_=FamilyEnrollment.objects.get_or_create(program=p,member=m,defaults={'parent_name':'والد نمونه','consent_at':timezone.now(),'terms_snapshot':p.terms})
c,_=Child.objects.get_or_create(enrollment=e,name='فرزند نمونه',defaults={'birth_date':date(2016,1,1),'sex':'f'})
GrowthRecord.objects.get_or_create(child=c,measured_on=date(2026,10,1),defaults={'height_cm':138,'weight_kg':34,'interpretation':'این گزارش صرفاً دادهٔ آزمایشی است.','clinician':u})
s=SessionStore();s['gl_customer_member_id']=m.pk;s['gl_customer_auth_at']=timezone.now().timestamp();s.save();users['parent']=s.session_key
open('/tmp/school-browser-fixture.json','w').write(json.dumps({'sessions':users,'program':p.pk,'token':str(p.token),'enrollment':e.pk,'child':c.pk}))
print('Local synthetic fixture ready')
