import uuid

from django.db import models
from django.utils import timezone

from core.models import UUIDModel


class SubscriptionPlan(UUIDModel):
    class Code(models.TextChoices):
        STARTER = "starter", "Starter"
        PROFESSIONAL = "professional", "Professional"
        ENTERPRISE = "enterprise", "Enterprise"

    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=50, choices=Code.choices, unique=True)
    description = models.TextField(blank=True)
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    price_yearly = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    # Resource limits (-1 denotes unlimited)
    max_users = models.IntegerField(default=3, help_text="-1 for unlimited users")
    max_medicines = models.IntegerField(default=500, help_text="-1 for unlimited catalog items")
    max_branches = models.IntegerField(default=1, help_text="-1 for unlimited branches")

    # Feature flags
    has_reports = models.BooleanField(default=False)
    has_sms = models.BooleanField(default=False)
    has_backups = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("price_monthly",)

    def __str__(self) -> str:
        return f"{self.name} Plan"


class TenantSubscription(UUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PENDING_APPROVAL = "pending_approval", "Pending Approval"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    class BillingCycle(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    tenant = models.OneToOneField(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, related_name="tenant_subscriptions"
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING_APPROVAL
    )
    billing_cycle = models.CharField(
        max_length=20, choices=BillingCycle.choices, default=BillingCycle.MONTHLY
    )
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    auto_renew = models.BooleanField(default=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.tenant.name} - {self.plan.name} ({self.status})"

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at or self.status == self.Status.EXPIRED

    @property
    def days_until_expiration(self) -> int:
        delta = self.expires_at - timezone.now()
        return max(0, delta.days)


class PaymentRequest(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending Approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="payment_requests"
    )
    plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, related_name="payment_requests"
    )
    billing_cycle = models.CharField(
        max_length=20, choices=TenantSubscription.BillingCycle.choices
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_id = models.CharField(max_length=100, unique=True, db_index=True)
    payment_method = models.CharField(
        max_length=50, help_text="e.g. Telebirr, CBE Birr, Bank Transfer"
    )
    proof_attachment = models.CharField(
        max_length=255, blank=True, help_text="Optional receipt URL or file ref"
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    rejection_reason = models.TextField(blank=True)

    submitted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_payment_requests",
    )
    reviewed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_payment_requests",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"PaymentRequest({self.transaction_id}, {self.tenant.name}, {self.status})"


class SubscriptionNotification(UUIDModel):
    class Type(models.TextChoices):
        EXPIRING_7_DAYS = "expiring_7_days", "Expiring in 7 Days"
        EXPIRING_3_DAYS = "expiring_3_days", "Expiring in 3 Days"
        EXPIRING_1_DAY = "expiring_1_day", "Expiring in 1 Day"
        EXPIRED = "expired", "Subscription Expired"

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="subscription_notifications",
    )
    notification_type = models.CharField(max_length=30, choices=Type.choices)
    message = models.TextField()
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("tenant", "notification_type")),
        ]

    def __str__(self) -> str:
        return f"SubscriptionNotification({self.tenant.name}, {self.notification_type})"
