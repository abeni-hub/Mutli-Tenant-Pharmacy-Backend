from __future__ import annotations
import sys

from django.core.management.base import BaseCommand
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.subscriptions.models import PaymentRequest, SubscriptionNotification, TenantSubscription
from apps.tenants.models import Branch, FeatureFlag, Membership, Tenant, UserInvitation


class Command(BaseCommand):
    help = "Verify PostgreSQL database truth for the Super Admin platform integration."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== SUPER ADMIN DATABASE TRUTH VERIFICATION ==="))

        has_failure = False

        # 1. Super Admin User Check
        sa_email = "superadmin@abeni.test"
        sa_user = User.objects.filter(email=sa_email).first()

        if not sa_user:
            self.stdout.write(self.style.ERROR(f"[FAIL] Super Admin user '{sa_email}' does NOT exist in PostgreSQL."))
            has_failure = True
        else:
            self.stdout.write(self.style.SUCCESS(f"[PASS] Super Admin User: {sa_user.email} (ID: {sa_user.id})"))
            self.stdout.write(f"       Name: {sa_user.full_name}")
            self.stdout.write(f"       is_superuser: {sa_user.is_superuser}")
            self.stdout.write(f"       is_staff: {sa_user.is_staff}")
            self.stdout.write(f"       is_active: {sa_user.is_active}")
            if not sa_user.is_superuser or not sa_user.is_staff:
                self.stdout.write(self.style.ERROR("       [MISMATCH] Super Admin must have is_superuser=True and is_staff=True!"))
                has_failure = True

        # 2. Tenants Check
        total_tenants = Tenant.objects.count()
        active_tenants = Tenant.objects.filter(is_active=True).count()
        suspended_tenants = Tenant.objects.filter(is_active=False).count()

        self.stdout.write(self.style.MIGRATE_HEADING("\n--- TENANTS ---"))
        self.stdout.write(f"Total Tenants: {total_tenants}")
        self.stdout.write(f"Active Tenants: {active_tenants}")
        self.stdout.write(f"Suspended Tenants: {suspended_tenants}")

        if total_tenants == 0:
            self.stdout.write(self.style.ERROR("       [FAIL] No tenant records found in database!"))
            has_failure = True

        for t in Tenant.objects.all():
            status_str = "ACTIVE" if t.is_active else "SUSPENDED"
            self.stdout.write(f"  • {t.name} (Slug: {t.slug}) — {status_str}")

        # 3. Branches Check
        total_branches = Branch.objects.count()
        self.stdout.write(self.style.MIGRATE_HEADING("\n--- BRANCHES ---"))
        self.stdout.write(f"Total Branches: {total_branches}")
        for t in Tenant.objects.all():
            t_branches = t.branches.all()
            b_names = ", ".join([f"{b.name} ({b.code})" for b in t_branches]) or "None"
            self.stdout.write(f"  • {t.name}: {t_branches.count()} branches [{b_names}]")

        # 4. Users & Roles Check
        total_users = User.objects.count()
        sa_count = User.objects.filter(is_superuser=True).count()
        owners_count = Membership.objects.filter(role=Membership.Role.OWNER, is_active=True).values("user").distinct().count()
        pharmacists_count = Membership.objects.filter(role=Membership.Role.PHARMACIST, is_active=True).values("user").distinct().count()
        cashiers_count = Membership.objects.filter(role=Membership.Role.CASHIER, is_active=True).values("user").distinct().count()

        self.stdout.write(self.style.MIGRATE_HEADING("\n--- USERS BY ROLE ---"))
        self.stdout.write(f"Total Users: {total_users}")
        self.stdout.write(f"Super Admins: {sa_count}")
        self.stdout.write(f"Owners: {owners_count}")
        self.stdout.write(f"Pharmacists: {pharmacists_count}")
        self.stdout.write(f"Cashiers: {cashiers_count}")

        # 5. Subscriptions Check
        total_subs = TenantSubscription.objects.count()
        active_subs = TenantSubscription.objects.filter(status=TenantSubscription.Status.ACTIVE).count()
        expired_subs = TenantSubscription.objects.filter(status=TenantSubscription.Status.EXPIRED).count()

        self.stdout.write(self.style.MIGRATE_HEADING("\n--- SUBSCRIPTIONS ---"))
        self.stdout.write(f"Total Subscriptions: {total_subs}")
        self.stdout.write(f"Active Subscriptions: {active_subs}")
        self.stdout.write(f"Expired Subscriptions: {expired_subs}")

        # 6. Payments Check
        pending_payments = PaymentRequest.objects.filter(status=PaymentRequest.Status.PENDING).count()
        approved_payments = PaymentRequest.objects.filter(status=PaymentRequest.Status.APPROVED).count()
        rejected_payments = PaymentRequest.objects.filter(status=PaymentRequest.Status.REJECTED).count()

        self.stdout.write(self.style.MIGRATE_HEADING("\n--- PAYMENTS ---"))
        self.stdout.write(f"Pending Payments: {pending_payments}")
        self.stdout.write(f"Approved Payments: {approved_payments}")
        self.stdout.write(f"Rejected Payments: {rejected_payments}")

        # 7. Audit & Notifications & Flags & Invitations
        total_audits = AuditEvent.objects.count()
        total_notifs = SubscriptionNotification.objects.count()
        total_flags = FeatureFlag.objects.count()
        total_invites = UserInvitation.objects.count()

        self.stdout.write(self.style.MIGRATE_HEADING("\n--- SYSTEM LOGS & METRICS ---"))
        self.stdout.write(f"Audit Logs: {total_audits}")
        self.stdout.write(f"Notifications: {total_notifs}")
        self.stdout.write(f"Feature Flags: {total_flags}")
        self.stdout.write(f"User Invitations: {total_invites}")

        if has_failure:
            self.stdout.write(self.style.ERROR("\n=== VERIFICATION FAILED WITH MISMATCHES ==="))
            sys.exit(1)
        else:
            self.stdout.write(self.style.SUCCESS("\n=== VERIFICATION COMPLETED SUCCESSFULLY ==="))
