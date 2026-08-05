from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.subscriptions.models import PaymentRequest, SubscriptionPlan, TenantSubscription
from apps.tenants.models import Tenant
from apps.tenants.services import TenantCreateData, TenantService


@pytest.mark.django_db
class TestPlatformSuperAdmin:
    def setup_method(self):
        self.client = APIClient()
        self.superuser = User.objects.create_superuser(
            email="platform@abeni.test", password="Password123!"
        )
        self.owner = User.objects.create_user(
            email="platformowner@abeni.test", password="Password123!"
        )
        self.tenant = TenantService.create_for_owner(
            self.owner, TenantCreateData(name="Platform Test Pharmacy")
        )
        self.plan, _ = SubscriptionPlan.objects.get_or_create(
            code="enterprise",
            defaults={
                "name": "Enterprise",
                "price_monthly": 100.00,
                "price_yearly": 1000.00,
                "max_users": 20,
                "max_medicines": 1000,
                "max_branches": 5,
                "has_reports": True,
                "has_sms": True,
                "has_backups": True,
            },
        )
        self.subscription = TenantSubscription.objects.create(
            tenant=self.tenant,
            plan=self.plan,
            status=TenantSubscription.Status.ACTIVE,
            billing_cycle=TenantSubscription.BillingCycle.MONTHLY,
            starts_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.payment_request = PaymentRequest.objects.create(
            tenant=self.tenant,
            plan=self.plan,
            billing_cycle=TenantSubscription.BillingCycle.MONTHLY,
            amount=100.00,
            transaction_id="PLAT-1001",
            payment_method="Bank Transfer",
            submitted_by=self.owner,
            status=PaymentRequest.Status.PENDING,
        )

        self.superuser_token = self._get_token(self.superuser)
        self.owner_token = self._get_token(self.owner)

    def _get_token(self, user: User) -> str:
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)
        return str(refresh.access_token)

    def test_01_super_admin_can_access_platform_analytics_and_reports(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.superuser_token}")

        analytics_res = self.client.get("/api/v1/platform/analytics/")
        assert analytics_res.status_code == 200, analytics_res.data
        assert analytics_res.data["totals"]["tenant_count"] >= 1
        assert analytics_res.data["totals"]["active_tenant_count"] >= 1
        assert analytics_res.data["subscription_distribution"]

        reports_res = self.client.get("/api/v1/platform/reports/")
        assert reports_res.status_code == 200, reports_res.data
        assert "monthly_revenue" in reports_res.data
        assert "annual_revenue" in reports_res.data

    def test_02_non_super_admin_is_forbidden_from_platform_endpoints(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")

        analytics_res = self.client.get("/api/v1/platform/analytics/")
        subscriptions_res = self.client.get("/api/v1/platform/subscriptions/")
        payments_res = self.client.get("/api/v1/platform/payments/")

        assert analytics_res.status_code == 403
        assert subscriptions_res.status_code == 403
        assert payments_res.status_code == 403

    def test_03_super_admin_can_manage_tenant_lifecycle(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.superuser_token}")

        suspend_res = self.client.post(f"/api/v1/platform/tenants/{self.tenant.id}/suspend/")
        assert suspend_res.status_code == 200, suspend_res.data
        self.tenant.refresh_from_db()
        assert self.tenant.is_active is False

        reactivate_res = self.client.post(f"/api/v1/platform/tenants/{self.tenant.id}/reactivate/")
        assert reactivate_res.status_code == 200, reactivate_res.data
        self.tenant.refresh_from_db()
        assert self.tenant.is_active is True

    def test_04_super_admin_can_approve_payments_and_view_health(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.superuser_token}")

        payments_res = self.client.get("/api/v1/platform/payments/")
        assert payments_res.status_code == 200, payments_res.data
        assert payments_res.data["count"] >= 1

        approve_res = self.client.post(f"/api/v1/platform/payments/{self.payment_request.id}/approve/")
        assert approve_res.status_code == 200, approve_res.data
        self.payment_request.refresh_from_db()
        assert self.payment_request.status == PaymentRequest.Status.APPROVED

        health_res = self.client.get("/api/v1/platform/health/")
        assert health_res.status_code == 200, health_res.data
        assert health_res.data["status"] == "ok"
