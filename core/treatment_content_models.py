"""Structured, editable content attached to existing shared treatment master records."""
from django.conf import settings
from django.db import models


class TreatmentRichContent(models.Model):
    master_item=models.OneToOneField(
        'core.TreatmentCatalogItem',on_delete=models.PROTECT,related_name='rich_content',
    )
    is_active=models.BooleanField(default=True)
    cover_external_url=models.URLField(max_length=1300,blank=True)
    cover_file=models.ImageField(upload_to='treatment-content/covers/%Y/%m/',blank=True)
    intro_warning=models.TextField(blank=True)
    audio_external_url=models.URLField(max_length=1300,blank=True)
    audio_file=models.FileField(upload_to='treatment-content/audio/%Y/%m/',blank=True)
    origin=models.CharField(max_length=100,blank=True)
    imported_at=models.DateTimeField(null=True,blank=True)
    updated_at=models.DateTimeField(auto_now=True)

    class Meta:
        ordering=['master_item__name']

    def __str__(self):
        return str(self.master_item.name)

    @property
    def cover_url(self):
        return self.cover_file.url if self.cover_file else self.cover_external_url

    @property
    def audio_url(self):
        return self.audio_file.url if self.audio_file else self.audio_external_url


class TreatmentRichSection(models.Model):
    content=models.ForeignKey(
        TreatmentRichContent,on_delete=models.CASCADE,related_name='sections',
    )
    title=models.CharField(max_length=200)
    body=models.TextField(blank=True)
    sort_order=models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering=['sort_order','id']


class TreatmentRichMedia(models.Model):
    KINDS=[('image','تصویر'),('audio','صوت')]
    section=models.ForeignKey(
        TreatmentRichSection,on_delete=models.CASCADE,related_name='media',
    )
    kind=models.CharField(max_length=8,choices=KINDS,default='image')
    original_url=models.URLField(max_length=1300,blank=True)
    uploaded_file=models.FileField(upload_to='treatment-content/media/%Y/%m/',blank=True)
    sort_order=models.PositiveSmallIntegerField(default=0)
    # Image's original position before a numbered line of section.body; null = footer.
    inline_before_line=models.PositiveSmallIntegerField(null=True,blank=True)
    is_responsive_duplicate=models.BooleanField(default=False)

    class Meta:
        ordering=['sort_order','id']

    @property
    def url(self):
        return self.uploaded_file.url if self.uploaded_file else self.original_url
