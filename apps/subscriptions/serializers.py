from rest_framework import serializers

from apps.subscriptions.models import (
    PaymentRequest,
    SubscriptionNotification,
    SubscriptionPlan,
    TenantSubscription,
)


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = (
            "id",
            "name",
            "code",
            "description",
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
        read_only_fields = fields


class TenantSubscriptionSerializer(serializers.ModelSerializer):
    plan = SubscriptionPlanSerializer(read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    days_until_expiration = serializers.IntegerField(read_only=True)

    class Meta:
        model = TenantSubscription
        fields = (
            "id",
            "tenant",
            "tenant_name",
            "plan",
            "status",
            "billing_cycle",
            "starts_at",
            "expires_at",
            "auto_renew",
            "is_expired",
            "days_until_expiration",
        )
        read_only_fields = fields


class PaymentRequestSerializer(serializers.ModelSerializer):
    plan = SubscriptionPlanSerializer(read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    submitted_by_email = serializers.EmailField(
        source="submitted_by.email", read_only=True, default=None
    )
    reviewed_by_email = serializers.EmailField(
        source="reviewed_by.email", read_only=True, default=None
    )

    class Meta:
        model = PaymentRequest
        fields = (
            "id",
            "tenant",
            "tenant_name",
            "plan",
            "billing_cycle",
            "amount",
            "transaction_id",
            "payment_method",
            "proof_attachment",
            "status",
            "rejection_reason",
            "submitted_by_email",
            "reviewed_by_email",
            "reviewed_at",
            "created_at",
        )
        read_only_fields = fields


class PaymentRequestSubmitSerializer(serializers.Serializer):
    plan_id = serializers.UUIDField()
    billing_cycle = serializers.ChoiceField(
        choices=TenantSubscription.BillingCycle.choices
    )
    transaction_id = serializers.CharField(max_length=100)
    payment_method = serializers.CharField(max_length=50)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    proof_attachment = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )

    def validate_plan_id(self, value):
        try:
            plan = SubscriptionPlan.objects.get(id=value, is_active=True)
        except SubscriptionPlan.DoesNotExist:
            raise serializers.ValidationError("Invalid or inactive subscription plan.")
        return plan


class PaymentRequestRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, min_length=3)


class SubscriptionNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionNotification
        fields = (
            "id",
            "tenant",
            "notification_type",
            "message",
            "is_read",
            "created_at",
        )
        read_only_fields = ("id", "tenant", "notification_type", "message", "created_at")
