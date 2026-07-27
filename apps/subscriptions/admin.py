from django.contrib import admin

from apps.subscriptions.models import (
    PaymentRequest,
    SubscriptionNotification,
    SubscriptionPlan,
    TenantSubscription,
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "price_monthly",
        "price_yearly",
        "max_users",
        "max_medicines",
        "max_branches",
        "has_reports",
        "has_sms",
        "has_backups",
        "is_active",
    )
    list_filter = ("is_active", "has_reports", "has_sms", "has_backups")
    search_fields = ("name", "code")


@admin.register(TenantSubscription)
class TenantSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "tenant",
        "plan",
        "status",
        "billing_cycle",
        "starts_at",
        "expires_at",
        "auto_renew",
    )
    list_filter = ("status", "billing_cycle", "plan")
    search_fields = ("tenant__name", "plan__name")
    readonly_fields = ("starts_at",)


@admin.register(PaymentRequest)
class PaymentRequestAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_id",
        "tenant",
        "plan",
        "billing_cycle",
        "amount",
        "payment_method",
        "status",
        "submitted_by",
        "reviewed_by",
        "reviewed_at",
    )
    list_filter = ("status", "payment_method", "billing_cycle", "plan")
    search_fields = ("transaction_id", "tenant__name", "submitted_by__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(SubscriptionNotification)
class SubscriptionNotificationAdmin(admin.ModelAdmin):
    list_display = ("tenant", "notification_type", "is_read", "created_at")
    list_filter = ("notification_type", "is_read")
    search_fields = ("tenant__name", "message")
