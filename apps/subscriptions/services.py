"""
Subscription service module.

Handles payment request processing, automatic subscription activation/extension,
limit enforcement, and expiration warning notifications.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit.services import AuditService
from apps.subscriptions.models import (
    PaymentRequest,
    SubscriptionNotification,
    SubscriptionPlan,
    TenantSubscription,
)
from apps.tenants.models import Membership, Tenant


class SubscriptionService:
    @staticmethod
    @transaction.atomic
    def submit_payment_request(
        *,
        tenant: Tenant,
        plan: SubscriptionPlan,
        billing_cycle: str,
        transaction_id: str,
        payment_method: str,
        amount: float,
        submitted_by: User,
        proof_attachment: str = "",
    ) -> PaymentRequest:
        """Submit a new payment request for tenant subscription approval."""
        if PaymentRequest.objects.filter(transaction_id__iexact=transaction_id).exists():
            raise ValidationError(
                {"transaction_id": "A payment request with this transaction ID already exists."}
            )

        payment_request = PaymentRequest.objects.create(
            tenant=tenant,
            plan=plan,
            billing_cycle=billing_cycle,
            amount=amount,
            transaction_id=transaction_id,
            payment_method=payment_method,
            proof_attachment=proof_attachment,
            submitted_by=submitted_by,
            status=PaymentRequest.Status.PENDING,
        )

        AuditService.record(
            tenant=tenant,
            actor=submitted_by,
            action="create",
            entity_type="subscriptions.PaymentRequest",
            entity_id=payment_request.id,
            metadata={
                "transaction_id": transaction_id,
                "plan": plan.name,
                "amount": str(amount),
            },
        )
        return payment_request

    @staticmethod
    @transaction.atomic
    def approve_payment_request(
        *,
        payment_request_id: UUID,
        reviewer: User,
    ) -> TenantSubscription:
        """
        Approve a payment request and automatically activate or extend the tenant's subscription.
        """
        try:
            req = PaymentRequest.objects.select_for_update().get(id=payment_request_id)
        except PaymentRequest.DoesNotExist:
            raise ValidationError("Payment request not found.")

        if req.status != PaymentRequest.Status.PENDING:
            raise ValidationError(f"Cannot approve a payment request with status '{req.status}'.")

        now = timezone.now()
        duration_days = 365 if req.billing_cycle == TenantSubscription.BillingCycle.YEARLY else 30

        # Retrieve existing subscription if any
        sub = TenantSubscription.objects.filter(tenant=req.tenant).first()

        if sub and sub.status == TenantSubscription.Status.ACTIVE and sub.expires_at > now:
            # Extend existing active subscription
            new_starts_at = sub.starts_at
            new_expires_at = sub.expires_at + timedelta(days=duration_days)
        else:
            # Start fresh or reactivate
            new_starts_at = now
            new_expires_at = now + timedelta(days=duration_days)

        if sub is None:
            sub = TenantSubscription.objects.create(
                tenant=req.tenant,
                plan=req.plan,
                status=TenantSubscription.Status.ACTIVE,
                billing_cycle=req.billing_cycle,
                starts_at=new_starts_at,
                expires_at=new_expires_at,
            )
        else:
            sub.plan = req.plan
            sub.billing_cycle = req.billing_cycle
            sub.status = TenantSubscription.Status.ACTIVE
            sub.starts_at = new_starts_at
            sub.expires_at = new_expires_at
            sub.save()

        # Update payment request
        req.status = PaymentRequest.Status.APPROVED
        req.reviewed_by = reviewer
        req.reviewed_at = now
        req.save()

        AuditService.record(
            tenant=req.tenant,
            actor=reviewer,
            action="update",
            entity_type="subscriptions.TenantSubscription",
            entity_id=sub.id,
            metadata={
                "status": "APPROVED",
                "plan": req.plan.name,
                "expires_at": sub.expires_at.isoformat(),
            },
        )
        return sub

    @staticmethod
    @transaction.atomic
    def reject_payment_request(
        *,
        payment_request_id: UUID,
        reviewer: User,
        reason: str,
    ) -> PaymentRequest:
        """Reject a payment request with a mandatory reason."""
        if not reason.strip():
            raise ValidationError({"rejection_reason": "A rejection reason is required."})

        try:
            req = PaymentRequest.objects.select_for_update().get(id=payment_request_id)
        except PaymentRequest.DoesNotExist:
            raise ValidationError("Payment request not found.")

        if req.status != PaymentRequest.Status.PENDING:
            raise ValidationError(f"Cannot reject a payment request with status '{req.status}'.")

        req.status = PaymentRequest.Status.REJECTED
        req.rejection_reason = reason
        req.reviewed_by = reviewer
        req.reviewed_at = timezone.now()
        req.save()

        AuditService.record(
            tenant=req.tenant,
            actor=reviewer,
            action="update",
            entity_type="subscriptions.PaymentRequest",
            entity_id=req.id,
            metadata={"status": "REJECTED", "reason": reason},
        )
        return req

    @staticmethod
    def get_tenant_usage_and_limits(tenant: Tenant) -> dict:
        """Get tenant's active plan limits alongside current usage counts."""
        sub = getattr(tenant, "subscription", None)
        if sub is None or sub.is_expired:
            plan_info = {
                "plan_name": "None / Expired",
                "max_users": 0,
                "max_medicines": 0,
                "max_branches": 0,
                "has_reports": False,
                "has_sms": False,
                "has_backups": False,
                "status": sub.status if sub else "expired",
            }
        else:
            plan = sub.plan
            plan_info = {
                "plan_name": plan.name,
                "max_users": plan.max_users,
                "max_medicines": plan.max_medicines,
                "max_branches": plan.max_branches,
                "has_reports": plan.has_reports,
                "has_sms": plan.has_sms,
                "has_backups": plan.has_backups,
                "status": sub.status,
                "expires_at": sub.expires_at,
                "days_until_expiration": sub.days_until_expiration,
            }

        # Current usage metrics
        current_users = Membership.objects.filter(tenant=tenant, is_active=True).count()
        # Catalog product count (if catalog app is loaded)
        try:
            from apps.catalog.models import Product
            current_medicines = Product.objects.filter(tenant=tenant).count()
        except (ImportError, RuntimeError):
            current_medicines = 0

        current_branches = 1  # Base default single branch

        return {
            "subscription": plan_info,
            "usage": {
                "current_users": current_users,
                "current_medicines": current_medicines,
                "current_branches": current_branches,
            },
        }

    @staticmethod
    def check_user_limit(tenant: Tenant) -> bool:
        """Return True if tenant can add another user membership, False if limit reached."""
        sub = getattr(tenant, "subscription", None)
        if sub is None or sub.is_expired:
            return False
        if sub.plan.max_users == -1:
            return True
        current_users = Membership.objects.filter(tenant=tenant, is_active=True).count()
        return current_users < sub.plan.max_users

    @staticmethod
    def check_medicine_limit(tenant: Tenant) -> bool:
        """Return True if tenant can add another product/medicine, False if limit reached."""
        sub = getattr(tenant, "subscription", None)
        if sub is None or sub.is_expired:
            return False
        if sub.plan.max_medicines == -1:
            return True
        try:
            from apps.catalog.models import Product
            current_medicines = Product.objects.filter(tenant=tenant).count()
        except (ImportError, RuntimeError):
            current_medicines = 0
        return current_medicines < sub.plan.max_medicines

    @staticmethod
    def process_expiration_notifications() -> list[SubscriptionNotification]:
        """
        Scan all active subscriptions and generate expiration alerts for tenants
        expiring in <=7 days, <=3 days, <=1 day, or expired.
        """
        now = timezone.now()
        notifications_created = []

        subscriptions = TenantSubscription.objects.select_related("tenant", "plan").all()

        for sub in subscriptions:
            # Expiration check
            if sub.expires_at <= now and sub.status != TenantSubscription.Status.EXPIRED:
                sub.status = TenantSubscription.Status.EXPIRED
                sub.save(update_fields=["status"])

                notif, created = SubscriptionNotification.objects.get_or_create(
                    tenant=sub.tenant,
                    notification_type=SubscriptionNotification.Type.EXPIRED,
                    defaults={
                        "message": f"Your subscription for plan '{sub.plan.name}' has expired. Please renew to regain full access."
                    },
                )
                if created:
                    notifications_created.append(notif)
                continue

            # Remaining days check
            days_left = sub.days_until_expiration
            if 0 < days_left <= 1:
                notif_type = SubscriptionNotification.Type.EXPIRING_1_DAY
                msg = f"URGENT: Your subscription for plan '{sub.plan.name}' expires tomorrow!"
            elif 1 < days_left <= 3:
                notif_type = SubscriptionNotification.Type.EXPIRING_3_DAYS
                msg = f"Warning: Your subscription for plan '{sub.plan.name}' expires in {days_left} days."
            elif 3 < days_left <= 7:
                notif_type = SubscriptionNotification.Type.EXPIRING_7_DAYS
                msg = f"Notice: Your subscription for plan '{sub.plan.name}' expires in {days_left} days."
            else:
                continue

            notif, created = SubscriptionNotification.objects.get_or_create(
                tenant=sub.tenant,
                notification_type=notif_type,
                defaults={"message": msg},
            )
            if created:
                notifications_created.append(notif)

        return notifications_created
