from django.contrib import admin

from .models import Claim, ServiceLine, Provider, Member, StatusHistory, IngestionLog, Payment, UserProfile


class ServiceLineInline(admin.TabularInline):
    model = ServiceLine
    extra = 0


class StatusHistoryInline(admin.TabularInline):
    model = StatusHistory
    extra = 0
    readonly_fields = ["from_status", "to_status", "reason", "actor", "created_at"]
    can_delete = False


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ["method", "amount", "scheduled_payment_date", "reference_number", "status", "executed_at"]
    can_delete = False


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = ["claim_number", "provider", "member", "status", "total_claim_amount", "total_approved_amount", "updated_at"]
    list_filter = ["status", "claim_type"]
    search_fields = ["claim_number", "authorization_number"]
    inlines = [ServiceLineInline, StatusHistoryInline, PaymentInline]


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ["provider_id", "name", "is_active"]
    search_fields = ["provider_id", "name"]


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ["member_id", "name", "membership_status", "membership_effective_date"]
    search_fields = ["member_id", "name"]


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "role"]
    list_filter = ["role"]


admin.site.register(ServiceLine)
admin.site.register(StatusHistory)
admin.site.register(IngestionLog)
admin.site.register(Payment)