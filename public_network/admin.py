from django.contrib import admin

from .models import PublicNetworkMember


@admin.register(PublicNetworkMember)
class PublicNetworkMemberAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'sponsor', 'source', 'is_active', 'created_at')
    list_filter = ('source', 'is_active', 'created_at')
    search_fields = ('user__first_name', 'user__last_name', 'user__username', 'phone', 'code')
    readonly_fields = ('code', 'source_url', 'created_at', 'updated_at')
