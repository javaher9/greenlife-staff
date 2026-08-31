from django.contrib import admin
from .models import Branch,EmployeeProfile,Task,Announcement,DailyReport,SOPDocument,LeaveRequest,Attendance, JobDutyTemplate, Guideline, GuidelineAcknowledgement, DeviceIssue
@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display=('name','is_active','geofence_enabled','attendance_radius_m','latitude','longitude')
    list_editable=('geofence_enabled','attendance_radius_m')

@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display=('user','branch','role','job_title','shift_group','is_active')
    list_filter=('branch','role','shift_group','is_active')
    search_fields=('user__username','user__first_name','user__last_name','job_title','employee_code')
    autocomplete_fields=('user',)

admin.site.register(Task); admin.site.register(Announcement); admin.site.register(SOPDocument); admin.site.register(LeaveRequest)
@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display=('user','branch','date','check_in','check_out','status','check_in_location_status','check_in_distance_m')
    list_filter=('branch','date','status','check_in_location_status')
    search_fields=('user__username','user__first_name','user__last_name')
@admin.register(DailyReport)
class DailyReportAdmin(admin.ModelAdmin):
    list_display=('user','branch','process_status','created_at'); list_filter=('branch','process_status','created_at'); search_fields=('user__username','user__first_name','user__last_name','text','transcript','ai_summary')

from .models import KPIRecord, ScoreEvent
admin.site.register(KPIRecord)
admin.site.register(ScoreEvent)

from .models import FinancialTransaction, IntegrationSyncLog
admin.site.register(FinancialTransaction)
admin.site.register(IntegrationSyncLog)

from .models import WorkShift, ShiftAssignment, ShiftGroup, AttendanceCorrectionRequest, StaffNotification
@admin.register(WorkShift)
class WorkShiftAdmin(admin.ModelAdmin):
    list_display=('name','branch','start_time','end_time','grace_minutes','report_required','is_active')
    list_filter=('branch','is_active','report_required')
    search_fields=('name','branch__name')

@admin.register(ShiftGroup)
class ShiftGroupAdmin(admin.ModelAdmin):
    list_display=('name','branch','default_shift','is_active')
    list_filter=('branch','is_active')
    search_fields=('name',)
    autocomplete_fields=('default_shift',)

@admin.register(ShiftAssignment)
class ShiftAssignmentAdmin(admin.ModelAdmin):
    list_display=('user','shift','date','created_by')
    list_filter=('shift__branch','date','shift')
    search_fields=('user__username','user__first_name','user__last_name')
admin.site.register(AttendanceCorrectionRequest)
admin.site.register(StaffNotification)

from .models import (
    CampSite, CampMembership, CampPurchaseRequest, CampInvoice,
    CampInventoryItem, CampInventoryMovement, CampWorker, CampWorkerAttendance,
    CampProject, CampDailyTask, CampFoodPlan, CampDailyPhoto, CampCommanderCheck
)
admin.site.register(CampSite)
admin.site.register(CampMembership)
admin.site.register(CampPurchaseRequest)
admin.site.register(CampInvoice)
admin.site.register(CampInventoryItem)
admin.site.register(CampInventoryMovement)
admin.site.register(CampWorker)
admin.site.register(CampWorkerAttendance)
admin.site.register(CampProject)
admin.site.register(CampDailyTask)
admin.site.register(CampFoodPlan)
admin.site.register(CampDailyPhoto)
admin.site.register(CampCommanderCheck)


@admin.register(JobDutyTemplate)
class JobDutyTemplateAdmin(admin.ModelAdmin):
    list_display=('title','branch','job_title','is_active')
    list_filter=('branch','is_active')
    search_fields=('title','job_title','description')

@admin.register(Guideline)
class GuidelineAdmin(admin.ModelAdmin):
    list_display=('title','audience','branch','job_title','is_required','is_active','published_at')
    list_filter=('audience','branch','is_required','is_active')
    search_fields=('title','body','job_title')

@admin.register(GuidelineAcknowledgement)
class GuidelineAcknowledgementAdmin(admin.ModelAdmin):
    list_display=('guideline','user','acknowledged_at')
    list_filter=('guideline','acknowledged_at')
    search_fields=('user__username','user__first_name','user__last_name','guideline__title')


@admin.register(DeviceIssue)
class DeviceIssueAdmin(admin.ModelAdmin):
    list_display=('device_name','reporter','branch','status','created_at','resolved_at')
    list_filter=('status','branch','created_at')
    search_fields=('device_name','description','reporter__username','reporter__first_name','reporter__last_name')


from .models import ReferralProfile, ReferralLead, ReferralSale

@admin.register(ReferralProfile)
class ReferralProfileAdmin(admin.ModelAdmin):
    list_display=('user','referral_code','sponsor','phone','is_active','sync_status','created_at')
    list_filter=('is_active','sync_status','created_at')
    search_fields=('user__first_name','user__last_name','user__username','phone','referral_code','crm_id')
    autocomplete_fields=('user','sponsor','created_by')

@admin.register(ReferralLead)
class ReferralLeadAdmin(admin.ModelAdmin):
    list_display=('full_name','phone','referrer','status','source','assigned_to','next_follow_up','sync_status','created_at')
    list_filter=('status','source','sync_status','created_at')
    search_fields=('full_name','phone','alternate_phone','referrer__referral_code','referrer__user__first_name','referrer__user__last_name','crm_id')
    autocomplete_fields=('referrer','assigned_to','created_by')

@admin.register(ReferralSale)
class ReferralSaleAdmin(admin.ModelAdmin):
    list_display=('lead','sale_date','amount','direct_commission','level_two_commission','status','sync_status')
    list_filter=('status','sync_status','sale_date')
    search_fields=('lead__full_name','lead__phone','crm_id')
    autocomplete_fields=('lead','recorded_by')
