from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import uuid

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.subscriptions.models import (
    PaymentRequest,
    SubscriptionNotification,
    SubscriptionPlan,
    TenantSubscription,
)
from apps.tenants.models import Branch, Membership, Tenant


class Command(BaseCommand):
    help = "Idempotently seed test data for the Super Admin platform integration."

    def handle(self, *args, **options):
        self.stdout.write("Seeding Super Admin platform test data...")

        # 1. Ensure Super Admin account
        super_admin_email = "superadmin@abeni.test"
        super_admin, _ = User.objects.get_or_create(
            email=super_admin_email,
            defaults={
                "first_name": "Super",
                "last_name": "Admin",
                "is_superuser": True,
                "is_staff": True,
                "is_active": True,
            },
        )
        if not super_admin.is_superuser or not super_admin.is_staff:
            super_admin.is_superuser = True
            super_admin.is_staff = True
            super_admin.save(update_fields=["is_superuser", "is_staff"])

        if not super_admin.check_password("SecurePassword123!"):
            super_admin.set_password("SecurePassword123!")
            super_admin.save(update_fields=["password"])

        # 2. Subscription Plans
        plans_data = [
            {
                "name": "Starter",
                "code": SubscriptionPlan.Code.STARTER,
                "description": "Basic single-location pharmacy plan",
                "price_monthly": Decimal("49.00"),
                "price_yearly": Decimal("490.00"),
                "max_users": 3,
                "max_medicines": 500,
                "max_branches": 1,
                "has_reports": True,
                "has_sms": False,
                "has_backups": False,
            },
            {
                "name": "Professional",
                "code": SubscriptionPlan.Code.PROFESSIONAL,
                "description": "Multi-location growing pharmacy network",
                "price_monthly": Decimal("99.00"),
                "price_yearly": Decimal("990.00"),
                "max_users": 10,
                "max_medicines": 5000,
                "max_branches": 3,
                "has_reports": True,
                "has_sms": True,
                "has_backups": True,
            },
            {
                "name": "Enterprise",
                "code": SubscriptionPlan.Code.ENTERPRISE,
                "description": "Unlimited full enterprise pharmacy solution",
                "price_monthly": Decimal("199.00"),
                "price_yearly": Decimal("1990.00"),
                "max_users": -1,
                "max_medicines": -1,
                "max_branches": -1,
                "has_reports": True,
                "has_sms": True,
                "has_backups": True,
            },
        ]

        plans_dict = {}
        for pd in plans_data:
            plan, _ = SubscriptionPlan.objects.update_or_create(
                code=pd["code"],
                defaults=pd,
            )
            plans_dict[pd["code"]] = plan

        # 3. Seed Tenants & Owners
        tenants_specs = [
            {
                "name": "Meridian Pharma",
                "slug": "meridian-pharma",
                "owner_email": "owner.meridian@abeni.test",
                "is_active": True,
                "reg_no": "MP-8801",
                "plan_code": SubscriptionPlan.Code.ENTERPRISE,
                "sub_status": TenantSubscription.Status.ACTIVE,
                "branches": [
                    {"name": "Main Branch", "code": "MP-MAIN", "address": "Bole Road, Addis Ababa", "phone": "+251911000001", "is_main": True},
                    {"name": "Bole Branch", "code": "MP-BOLE", "address": "Bole Medhanialem, Addis Ababa", "phone": "+251911000002", "is_main": False},
                ],
            },
            {
                "name": "Abeni Community Pharmacy",
                "slug": "abeni-community-pharmacy",
                "owner_email": "owner.abeni@abeni.test",
                "is_active": True,
                "reg_no": "ACP-4402",
                "plan_code": SubscriptionPlan.Code.PROFESSIONAL,
                "sub_status": TenantSubscription.Status.ACTIVE,
                "branches": [
                    {"name": "Main Branch", "code": "ACP-MAIN", "address": "Kazanchis, Addis Ababa", "phone": "+251911000003", "is_main": True},
                ],
            },
            {
                "name": "Addis Health Pharmacy",
                "slug": "addis-health-pharmacy",
                "owner_email": "owner.addis@abeni.test",
                "is_active": True,
                "reg_no": "AHP-9903",
                "plan_code": SubscriptionPlan.Code.STARTER,
                "sub_status": TenantSubscription.Status.ACTIVE,
                "branches": [
                    {"name": "Main Branch", "code": "AHP-MAIN", "address": "Piassa, Addis Ababa", "phone": "+251911000004", "is_main": True},
                ],
            },
            {
                "name": "Demo Suspended Pharmacy",
                "slug": "demo-suspended-pharmacy",
                "owner_email": "owner.suspended@abeni.test",
                "is_active": False,
                "reg_no": "DSP-1104",
                "plan_code": SubscriptionPlan.Code.STARTER,
                "sub_status": TenantSubscription.Status.EXPIRED,
                "branches": [
                    {"name": "Main Branch", "code": "DSP-MAIN", "address": "Sarbet, Addis Ababa", "phone": "+251911000005", "is_main": True},
                ],
            },
        ]

        for spec in tenants_specs:
            tenant, _ = Tenant.objects.update_or_create(
                slug=spec["slug"],
                defaults={
                    "name": spec["name"],
                    "registration_number": spec["reg_no"],
                    "is_active": spec["is_active"],
                },
            )

            # Create owner account if not exists
            owner, created = User.objects.get_or_create(
                email=spec["owner_email"],
                defaults={
                    "first_name": spec["name"].split()[0],
                    "last_name": "Owner",
                    "is_active": True,
                },
            )
            if created:
                owner.set_password("SecurePassword123!")
                owner.save(update_fields=["password"])

            # Create membership
            Membership.objects.update_or_create(
                tenant=tenant,
                user=owner,
                defaults={"role": Membership.Role.OWNER, "is_active": True},
            )

            # Seed branches
            for bspec in spec.get("branches", []):
                Branch.objects.update_or_create(
                    tenant=tenant,
                    code=bspec["code"],
                    defaults={
                        "name": bspec["name"],
                        "address": bspec["address"],
                        "phone": bspec["phone"],
                        "is_main": bspec["is_main"],
                        "is_active": spec["is_active"],
                    },
                )

            # Tenant Subscription
            plan = plans_dict[spec["plan_code"]]
            now = timezone.now()
            expires_at = now + timedelta(days=365) if spec["is_active"] else now - timedelta(days=1)
            TenantSubscription.objects.update_or_create(
                tenant=tenant,
                defaults={
                    "plan": plan,
                    "status": spec["sub_status"],
                    "billing_cycle": TenantSubscription.BillingCycle.YEARLY,
                    "starts_at": now - timedelta(days=30),
                    "expires_at": expires_at,
                    "auto_renew": True,
                },
            )

        # 4. Seed additional staff members for supported roles (Pharmacist & Cashier)
        meridian_tenant = Tenant.objects.get(slug="meridian-pharma")
        staff_specs = [
            ("pharmacist.meridian@abeni.test", "Pharmacist", "Meridian", Membership.Role.PHARMACIST),
            ("cashier.meridian@abeni.test", "Cashier", "Meridian", Membership.Role.CASHIER),
        ]
        for email, first_name, last_name, role in staff_specs:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={"first_name": first_name, "last_name": last_name, "is_active": True},
            )
            if created:
                user.set_password("SecurePassword123!")
                user.save(update_fields=["password"])
            Membership.objects.update_or_create(
                tenant=meridian_tenant,
                user=user,
                defaults={"role": role, "is_active": True},
            )

        # 5. Payment Requests
        abeni_tenant = Tenant.objects.get(slug="abeni-community-pharmacy")
        addis_tenant = Tenant.objects.get(slug="addis-health-pharmacy")

        payments_specs = [
            {
                "tx_id": "TXN-2026-8801",
                "tenant": meridian_tenant,
                "plan": plans_dict[SubscriptionPlan.Code.ENTERPRISE],
                "cycle": TenantSubscription.BillingCycle.YEARLY,
                "amount": Decimal("1990.00"),
                "method": "Bank Transfer",
                "status": PaymentRequest.Status.APPROVED,
                "submitted_by": meridian_tenant.memberships.first().user,
                "reviewed_by": super_admin,
                "reviewed_at": timezone.now(),
            },
            {
                "tx_id": "TXN-2026-4402",
                "tenant": abeni_tenant,
                "plan": plans_dict[SubscriptionPlan.Code.PROFESSIONAL],
                "cycle": TenantSubscription.BillingCycle.MONTHLY,
                "amount": Decimal("99.00"),
                "method": "Telebirr",
                "status": PaymentRequest.Status.PENDING,
                "submitted_by": abeni_tenant.memberships.first().user,
                "reviewed_by": None,
                "reviewed_at": None,
            },
            {
                "tx_id": "TXN-2026-9903",
                "tenant": addis_tenant,
                "plan": plans_dict[SubscriptionPlan.Code.STARTER],
                "cycle": TenantSubscription.BillingCycle.MONTHLY,
                "amount": Decimal("49.00"),
                "method": "CBE Birr",
                "status": PaymentRequest.Status.REJECTED,
                "rejection_reason": "Receipt number not matching transaction record.",
                "submitted_by": addis_tenant.memberships.first().user,
                "reviewed_by": super_admin,
                "reviewed_at": timezone.now(),
            },
        ]

        for ps in payments_specs:
            PaymentRequest.objects.update_or_create(
                transaction_id=ps["tx_id"],
                defaults={
                    "tenant": ps["tenant"],
                    "plan": ps["plan"],
                    "billing_cycle": ps["cycle"],
                    "amount": ps["amount"],
                    "payment_method": ps["method"],
                    "status": ps["status"],
                    "rejection_reason": ps.get("rejection_reason", ""),
                    "submitted_by": ps["submitted_by"],
                    "reviewed_by": ps["reviewed_by"],
                    "reviewed_at": ps["reviewed_at"],
                },
            )

        # 6. Audit Events
        audit_samples = [
            ("create", "tenants.Tenant", meridian_tenant.id, {"name": meridian_tenant.name}),
            ("update", "tenants.Tenant", abeni_tenant.id, {"status": "active"}),
            ("update", "subscriptions.PaymentRequest", meridian_tenant.id, {"status": "approved"}),
        ]
        for action, entity_type, entity_id, meta in audit_samples:
            AuditEvent.objects.get_or_create(
                tenant=meridian_tenant,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                defaults={"actor": super_admin, "metadata": meta},
            )

        # 7. Subscription Notifications
        SubscriptionNotification.objects.get_or_create(
            tenant=abeni_tenant,
            notification_type=SubscriptionNotification.Type.EXPIRING_7_DAYS,
            defaults={
                "message": "Subscription for Abeni Community Pharmacy expires in 7 days.",
                "is_read": False,
            },
        )

        self.stdout.write(self.style.SUCCESS("Successfully seeded Super Admin platform demo data!"))
