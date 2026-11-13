from io import BytesIO
from PIL import Image
from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import Branch, CustomerPortalMember, CustomerIntakePhoto, CustomerServiceRequest, StaffNotification

class IntakeTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='intake test')
        self.member=CustomerPortalMember.objects.create(phone='09121110000',full_name='Test Person',referral_code='intake1')
        s=self.client.session;s['gl_customer_member_id']=self.member.pk;s['gl_customer_auth_at']=timezone.now().timestamp();s.save()
        self.url='/customer/request/visit/'
        self.data={'full_name':'Test Person','branch':str(self.branch.pk),'city':'Tehran','goal':'Consultation','photo_consent':'yes'}
    def photo(self):
        b=BytesIO();Image.new('RGB',(300,300),'green').save(b,'PNG');return SimpleUploadedFile('test.png',b.getvalue(),'image/png')
    def staff(self,role,branch=None):
        u=User.objects.create_user(username=role+str(User.objects.count()));p=u.profile;p.role=role;p.branch=branch or self.branch;p.save();c=Client();c.force_login(u);return c
    def test_private_owner_staff_and_other_accounts(self):
        staff=self.staff('call_center')
        self.assertEqual(self.client.post(self.url,{**self.data,'photos':self.photo()}).status_code,302)
        photo=CustomerIntakePhoto.objects.get();url=f'/customer/intake/photo/{photo.public_id}/'
        self.assertEqual(photo.intake.request.member_id,self.member.pk)
        self.assertEqual(photo.intake.city,'Tehran')
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(self.client.get(url)['Cache-Control'],'private, no-store')
        self.assertEqual(Client().get(url).status_code,404)
        other=CustomerPortalMember.objects.create(phone='09121110001',referral_code='intake2');c=Client();s=c.session;s['gl_customer_member_id']=other.pk;s['gl_customer_auth_at']=timezone.now().timestamp();s.save()
        self.assertEqual(c.get(url).status_code,404)
        self.assertEqual(staff.get(url).status_code,200)
        self.assertContains(staff.get('/staff/customer-requests/'),url)
        wrong=self.staff('manager',Branch.objects.create(name='other'));self.assertEqual(wrong.get(url).status_code,404)
        self.assertEqual(self.staff('consultant').get(url).status_code,404)
        self.assertTrue(StaffNotification.objects.exists())
        self.client.post(self.url,{**self.data,'photos':self.photo()})
        self.assertEqual(CustomerServiceRequest.objects.count(),1)
        self.assertEqual(CustomerIntakePhoto.objects.count(),1)
    def test_rejected_uploads_create_no_records(self):
        cases=[{'photo_consent':'','photos':self.photo()},{'photos':SimpleUploadedFile('fake.jpg',b'not-image','image/jpeg')},{'photos':[self.photo() for _ in range(4)]},{'age':'999'},{'branch':'not-an-id'}]
        for fields in cases:
            r=self.client.post(self.url,{**self.data,**fields});self.assertEqual(r.status_code,200);self.assertFalse(CustomerServiceRequest.objects.exists())
    def test_optional_photos_and_preserved_values(self):
        r=self.client.post(self.url,{**self.data,'branch':''});self.assertContains(r,'Tehran')
        r=self.client.post(self.url,self.data);self.assertEqual(r.status_code,302);self.assertEqual(CustomerIntakePhoto.objects.count(),0)
    def test_guest_cannot_submit(self):
        self.assertEqual(Client().post(self.url,self.data).status_code,302);self.assertFalse(CustomerServiceRequest.objects.exists())
