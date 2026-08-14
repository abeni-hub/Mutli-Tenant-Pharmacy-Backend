from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.subscriptions.models import (
    PaymentRequest,
    SubscriptionNotification,
    SubscriptionPlan,
    TenantSubscription,
)
from apps.subscriptions.services import SubscriptionService
from apps.tenants.models import Membership, Tenant
from apps.tenants.services import TenantCreateData, TenantService
from core.api.permissions import (
    HasActiveSubscription,
    RequiresReportsFeature,
    RequiresSMSFeature,
)


@pytest.mark.django_db
class TestSubscriptionSystem:
    def setup_method(self):
        self.client = APIClient()
        self.superadmin = User.objects.create_superuser(
            email="super@abeni.test", password="SuperPassword123!"
        )
        self.owner = User.objects.create_user(
            email="tenantowner@abeni.test", password="Password123!"
        )
        self.tenant = TenantService.create_for_owner(
            self.owner, TenantCreateData(name="Subscription Test Pharmacy")
        )

        self.starter_plan = SubscriptionPlan.objects.get(code="starter")
        self.pro_plan = SubscriptionPlan.objects.get(code="professional")
        self.enterprise_plan = SubscriptionPlan.objects.get(code="enterprise")

    def test_01_seed_plans_exist(self):
        assert self.starter_plan.max_users == 3
        assert self.starter_plan.max_medicines == 500
        assert self.starter_plan.has_reports is False
        assert self.starter_plan.has_sms is False

        assert self.pro_plan.max_users == 10
        assert self.pro_plan.max_medicines == 5000
        assert self.pro_plan.has_reports is True
        assert self.pro_plan.has_sms is True

        assert self.enterprise_plan.max_users == -1
        assert self.enterprise_plan.has_backups is True

    def test_02_submit_payment_request(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._get_token(self.owner)}")
        res = self.client.post(
            "/api/v1/subscriptions/payment-requests/",
            {
                "plan_id": str(self.pro_plan.id),
                "billing_cycle": "monthly",
                "transaction_id": "TX-TELEBIRR-998877",
                "payment_method": "Telebirr",
                "amount": "79.00",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )
        assert res.status_code == 201, res.data
        assert res.data["transaction_id"] == "TX-TELEBIRR-998877"
        assert res.data["status"] == "pending"

    def test_03_approve_payment_request_auto_activates_subscription(self):
        payment_req = SubscriptionService.submit_payment_request(
            tenant=self.tenant,
            plan=self.pro_plan,
            billing_cycle="monthly",
            transaction_id="TX-CBE-112233",
            payment_method="CBE Birr",
            amount=79.00,
            submitted_by=self.owner,
        )

        # Approve as superadmin
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._get_token(self.superadmin)}")
        res = self.client.post(
            f"/api/v1/subscriptions/payment-requests/{payment_req.id}/approve/",
            format="json",
        )
        assert res.status_code == 200, res.data
        assert res.data["subscription"]["status"] == "active"
        assert res.data["subscription"]["plan"]["code"] == "professional"

        # Verify DB TenantSubscription
        sub = TenantSubscription.objects.get(tenant=self.tenant)
        assert sub.status == TenantSubscription.Status.ACTIVE
        assert sub.plan == self.pro_plan
        assert sub.is_expired is False

    def test_04_reject_payment_request(self):
        payment_req = SubscriptionService.submit_payment_request(
            tenant=self.tenant,
            plan=self.starter_plan,
            billing_cycle="monthly",
            transaction_id="TX-FAIL-445566",
            payment_method="Bank Transfer",
            amount=29.00,
            submitted_by=self.owner,
        )

        # Reject as superadmin
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._get_token(self.superadmin)}")
        res = self.client.post(
            f"/api/v1/subscriptions/payment-requests/{payment_req.id}/reject/",
            {"reason": "Transaction ID not found in bank statement."},
            format="json",
        )
        assert res.status_code == 200
        assert res.data["payment_request"]["status"] == "rejected"
        assert res.data["payment_request"]["rejection_reason"] == "Transaction ID not found in bank statement."

    def test_05_limit_enforcement(self):
        # Attach Starter subscription (max_users=3)
        sub, _ = TenantSubscription.objects.update_or_create(
            tenant=self.tenant,
            defaults={
                "plan": self.starter_plan,
                "status": TenantSubscription.Status.ACTIVE,
                "billing_cycle": TenantSubscription.BillingCycle.MONTHLY,
                "starts_at": timezone.now(),
                "expires_at": timezone.now() + timedelta(days=30),
            },
        )
        self.tenant.refresh_from_db()

        # Current user count is 1 (owner)
        assert SubscriptionService.check_user_limit(self.tenant) is True

        # Add 2 more users (total = 3, max_users = 3 limit reached)
        u2 = User.objects.create_user(email="u2@abeni.test", password="Pass123!Password")
        u3 = User.objects.create_user(email="u3@abeni.test", password="Pass123!Password")
        Membership.objects.create(tenant=self.tenant, user=u2, role=Membership.Role.CASHIER)
        Membership.objects.create(tenant=self.tenant, user=u3, role=Membership.Role.PHARMACIST)

        # 3 users reached max_users limit of 3
        assert SubscriptionService.check_user_limit(self.tenant) is False

    def test_06_feature_permission_gates(self):
        # Attach Starter sub (has_sms=False, has_reports=False)
        sub, _ = TenantSubscription.objects.update_or_create(
            tenant=self.tenant,
            defaults={
                "plan": self.starter_plan,
                "status": TenantSubscription.Status.ACTIVE,
                "billing_cycle": TenantSubscription.BillingCycle.MONTHLY,
                "starts_at": timezone.now(),
                "expires_at": timezone.now() + timedelta(days=30),
            },
        )
        self.tenant.refresh_from_db()

        class DummyRequest:
            user = self.owner
            tenant_id = self.tenant.id

        perm_sms = RequiresSMSFeature()
        perm_reports = RequiresReportsFeature()

        assert perm_sms.has_permission(DummyRequest(), None) is False
        assert perm_reports.has_permission(DummyRequest(), None) is False

        # Upgrade sub to Pro (has_sms=True, has_reports=True)
        sub.plan = self.pro_plan
        sub.save()
        self.tenant.refresh_from_db()

        assert perm_sms.has_permission(DummyRequest(), None) is True
        assert perm_reports.has_permission(DummyRequest(), None) is True

    def test_07_expiration_warning_notifications(self):
        # Create subscription expiring in ~2.5 days
        sub, _ = TenantSubscription.objects.update_or_create(
            tenant=self.tenant,
            defaults={
                "plan": self.pro_plan,
                "status": TenantSubscription.Status.ACTIVE,
                "billing_cycle": TenantSubscription.BillingCycle.MONTHLY,
                "starts_at": timezone.now() - timedelta(days=28),
                "expires_at": timezone.now() + timedelta(days=2, hours=12),
            },
        )
        self.tenant.refresh_from_db()

        created_notifs = SubscriptionService.process_expiration_notifications()
        assert len(created_notifs) == 1
        assert created_notifs[0].notification_type == SubscriptionNotification.Type.EXPIRING_3_DAYS

    def _get_token(self, user: User) -> str:
        login_res = self.client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": "SuperPassword123!" if user.is_superuser else "Password123!"},
            format="json",
        )
        return login_res.data["access"]
