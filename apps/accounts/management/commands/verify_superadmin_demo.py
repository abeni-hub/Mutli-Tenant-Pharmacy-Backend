from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.subscriptions.models import (
    PaymentRequest,
    SubscriptionNotification,
    SubscriptionPlan,
    TenantSubscription,
)
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Non-modifying verification command reporting Super Admin platform database state."

    def handle(self, *args, **options):
        self.stdout.write("=== SUPER ADMIN PLATFORM DATA VERIFICATION ===")

        tenants_count = Tenant.objects.count()
        active_tenants_count = Tenant.objects.filter(is_active=True).count()
        suspended_tenants_count = Tenant.objects.filter(is_active=False).count()

        plans_count = SubscriptionPlan.objects.count()
        subscriptions_count = TenantSubscription.objects.count()
        payments_count = PaymentRequest.objects.count()

        audit_count = AuditEvent.objects.count()
        notifications_count = SubscriptionNotification.objects.count()

        superadmins_count = User.objects.filter(is_superuser=True).count()

        self.stdout.write(f"Tenants: Total={tenants_count}, Active={active_tenants_count}, Suspended={suspended_tenants_count}")
        self.stdout.write(f"Subscription Plans: {plans_count}")
        self.stdout.write(f"Tenant Subscriptions: {subscriptions_count}")
        self.stdout.write(f"Payment Requests: {payments_count}")
        self.stdout.write(f"Audit Events: {audit_count}")
        self.stdout.write(f"Notifications: {notifications_count}")
        self.stdout.write(f"Super Admin Users: {superadmins_count}")

        # Relationship Verification
        self.stdout.write("\n--- Tenant Subscriptions Summary ---")
        for sub in TenantSubscription.objects.select_related("tenant", "plan").all():
            self.stdout.write(f"  • {sub.tenant.name} ({sub.tenant.slug}) -> Plan: {sub.plan.name}, Status: {sub.status}")

        self.stdout.write("\n--- Payment Requests Summary ---")
        for pay in PaymentRequest.objects.select_related("tenant", "plan").all():
            self.stdout.write(f"  • TX: {pay.transaction_id} | Tenant: {pay.tenant.name} | Amount: {pay.amount} | Status: {pay.status}")

        self.stdout.write(self.style.SUCCESS("\nVerification complete!"))
