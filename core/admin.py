from django.contrib import admin
from .models import Branch,EmployeeProfile,Task,Announcement,DailyReport,SOPDocument,LeaveRequest,Attendance
admin.site.register(Branch); admin.site.register(EmployeeProfile); admin.site.register(Task); admin.site.register(Announcement); admin.site.register(SOPDocument); admin.site.register(LeaveRequest); admin.site.register(Attendance)
@admin.register(DailyReport)
class DailyReportAdmin(admin.ModelAdmin):
    list_display=('user','branch','process_status','created_at'); list_filter=('branch','process_status','created_at'); search_fields=('user__username','user__first_name','user__last_name','text','transcript','ai_summary')

from .models import KPIRecord, ScoreEvent
admin.site.register(KPIRecord)
admin.site.register(ScoreEvent)

from .models import FinancialTransaction, IntegrationSyncLog
admin.site.register(FinancialTransaction)
admin.site.register(IntegrationSyncLog)

from .models import WorkShift, ShiftAssignment, AttendanceCorrectionRequest, StaffNotification
admin.site.register(WorkShift)
admin.site.register(ShiftAssignment)
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
