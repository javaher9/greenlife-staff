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
