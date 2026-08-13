import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.subscriptions.models import PaymentRequest, SubscriptionPlan, TenantSubscription
from apps.tenants.models import Membership, Tenant
from apps.tenants.services import TenantCreateData, TenantService


@pytest.mark.django_db
class TestSuperAdminPlatformIntegration:
    def setup_method(self):
        self.client = APIClient()
        self.superadmin = User.objects.create_superuser(
            email="superadmin_test@abeni.test",
            password="SecurePassword123!",
            first_name="Super",
            last_name="Admin",
        )
        self.owner = User.objects.create_user(
            email="owner_test@abeni.test",
            password="SecurePassword123!",
            first_name="Owner",
            last_name="User",
        )
        self.pharmacist = User.objects.create_user(
            email="pharmacist_test@abeni.test",
            password="SecurePassword123!",
            first_name="Pharm",
            last_name="User",
        )
        self.cashier = User.objects.create_user(
            email="cashier_test@abeni.test",
            password="SecurePassword123!",
            first_name="Cashier",
            last_name="User",
        )

        self.tenant = TenantService.create_for_owner(self.owner, TenantCreateData(name="Test Platform Tenant"))
        Membership.objects.create(tenant=self.tenant, user=self.pharmacist, role=Membership.Role.PHARMACIST)
        Membership.objects.create(tenant=self.tenant, user=self.cashier, role=Membership.Role.CASHIER)

        self.plan = SubscriptionPlan.objects.create(
            name="Platform Enterprise Plan",
            code="platform_enterprise",
            price_monthly=199,
            price_yearly=1990,
        )

    def test_01_superadmin_tenant_crud_suspend_reactivate(self):
        self.client.force_authenticate(user=self.superadmin)

        # 1. List Tenants
        res_list = self.client.get("/api/v1/platform/tenants/")
        assert res_list.status_code == 200
        assert len(res_list.data) >= 1

        # 2. Create Tenant
        res_create = self.client.post(
            "/api/v1/platform/tenants/",
            {
                "name": "Newly Created Tenant",
                "registration_number": "NCT-101",
                "owner_email": "newowner@abeni.test",
            },
            format="json",
        )
        assert res_create.status_code == 201
        new_tenant_id = res_create.data["id"]
        assert Tenant.objects.filter(id=new_tenant_id).exists()

        # 3. Suspend Tenant
        res_suspend = self.client.post(f"/api/v1/platform/tenants/{new_tenant_id}/suspend/")
        assert res_suspend.status_code == 200
        assert res_suspend.data["is_active"] is False
        assert Tenant.objects.get(id=new_tenant_id).is_active is False

        # 4. Reactivate Tenant
        res_reactivate = self.client.post(f"/api/v1/platform/tenants/{new_tenant_id}/reactivate/")
        assert res_reactivate.status_code == 200
        assert res_reactivate.data["is_active"] is True
        assert Tenant.objects.get(id=new_tenant_id).is_active is True

    def test_02_superadmin_payment_approval_and_rejection_workflow(self):
        self.client.force_authenticate(user=self.superadmin)

        payment = PaymentRequest.objects.create(
            tenant=self.tenant,
            plan=self.plan,
            billing_cycle="yearly",
            amount=1990,
            transaction_id="TXN-TEST-WORKFLOW-01",
            payment_method="Telebirr",
            submitted_by=self.owner,
        )

        # List payments
        res_list = self.client.get("/api/v1/platform/payments/")
        assert res_list.status_code == 200
        assert res_list.data["count"] >= 1

        # Verify payment
        res_verify = self.client.post(f"/api/v1/platform/payments/{payment.id}/verify/")
        assert res_verify.status_code == 200

        # Approve payment
        res_approve = self.client.post(f"/api/v1/platform/payments/{payment.id}/approve/")
        assert res_approve.status_code == 200

        payment.refresh_from_db()
        assert TenantSubscription.objects.filter(tenant=self.tenant, plan=self.plan).exists()

        # Test Rejecting another payment
        payment_reject = PaymentRequest.objects.create(
            tenant=self.tenant,
            plan=self.plan,
            billing_cycle="monthly",
            amount=199,
            transaction_id="TXN-TEST-REJECT-02",
            payment_method="Bank Transfer",
            submitted_by=self.owner,
        )
        res_reject = self.client.post(
            f"/api/v1/platform/payments/{payment_reject.id}/reject/",
            {"reason": "Invalid payment proof."},
            format="json",
        )
        assert res_reject.status_code == 200
        payment_reject.refresh_from_db()
        assert payment_reject.status == PaymentRequest.Status.REJECTED

    def test_03_superadmin_analytics_audit_health_notifications(self):
        self.client.force_authenticate(user=self.superadmin)

        # Analytics
        analytics_res = self.client.get("/api/v1/platform/analytics/")
        assert analytics_res.status_code == 200
        assert "totals" in analytics_res.data

        # Audit logs
        audit_res = self.client.get("/api/v1/platform/audit-logs/")
        assert audit_res.status_code == 200
        assert "results" in audit_res.data

        # Notifications
        notifications_res = self.client.get("/api/v1/platform/notifications/")
        assert notifications_res.status_code == 200
        assert "notifications" in notifications_res.data

        # Health
        health_res = self.client.get("/api/v1/platform/health/")
        assert health_res.status_code == 200
        assert health_res.data["status"] == "ok"

    def test_04_permissions_forbidden_for_non_superadmin(self):
        for non_admin_user in [self.owner, self.pharmacist, self.cashier]:
            self.client.force_authenticate(user=non_admin_user)

            res_tenants = self.client.get("/api/v1/platform/tenants/")
            assert res_tenants.status_code == 403

            res_payments = self.client.get("/api/v1/platform/payments/")
            assert res_payments.status_code == 403

            res_analytics = self.client.get("/api/v1/platform/analytics/")
            assert res_analytics.status_code == 403
