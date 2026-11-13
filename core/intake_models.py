"""Private intake attachments live in the database, never public MEDIA_ROOT."""
import uuid
from django.db import models
class CustomerIntake(models.Model):
    request=models.OneToOneField('core.CustomerServiceRequest',on_delete=models.CASCADE,related_name='intake')
    city=models.CharField(max_length=100,blank=True)
    address=models.CharField(max_length=400,blank=True)
    goal=models.CharField(max_length=300,blank=True)
    age=models.PositiveSmallIntegerField(null=True,blank=True)
    consent_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
class CustomerIntakePhoto(models.Model):
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    intake=models.ForeignKey(CustomerIntake,on_delete=models.CASCADE,related_name='photos')
    content=models.BinaryField()
    created_at=models.DateTimeField(auto_now_add=True)

class CustomerRequestEvent(models.Model):
    request=models.ForeignKey('core.CustomerServiceRequest',on_delete=models.CASCADE,related_name='followup_events')
    actor=models.ForeignKey('auth.User',on_delete=models.SET_NULL,null=True)
    action=models.CharField(max_length=40)
    note=models.CharField(max_length=1000,blank=True)
    status=models.CharField(max_length=12)
    next_followup_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-created_at','-pk']
