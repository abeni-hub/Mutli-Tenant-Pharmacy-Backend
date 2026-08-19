import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditEvent
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

    def test_05_auth_me_superadmin_identity(self):
        self.client.force_authenticate(user=self.superadmin)
        res = self.client.get("/api/v1/auth/me/")
        assert res.status_code == 200
        assert res.data["email"] == "superadmin_test@abeni.test"
        assert res.data["is_superuser"] is True
        assert res.data["is_staff"] is True
        assert res.data["role"] == "super_admin"

    def test_06_feature_flag_toggle_and_audit_logging(self):
        self.client.force_authenticate(user=self.superadmin)

        # 1. Fetch flags
        res_flags = self.client.get("/api/v1/platform/feature-flags/")
        assert res_flags.status_code == 200
        assert "feature_flags" in res_flags.data

        # 2. Toggle flag
        res_toggle = self.client.post("/api/v1/platform/feature-flags/reports/toggle/")
        assert res_toggle.status_code == 200
        assert "is_enabled" in res_toggle.data

        # 3. Assert Audit log recorded
        assert AuditEvent.objects.filter(entity_type="tenants.FeatureFlag", action="update").exists()

    def test_07_user_invitation_creation(self):
        self.client.force_authenticate(user=self.superadmin)

        res_invite = self.client.post(
            "/api/v1/platform/users/invite/",
            {"email": "invited_test@abeni.test", "role": "pharmacist", "tenant_id": str(self.tenant.id)},
            format="json",
        )
        assert res_invite.status_code == 201
        assert res_invite.data["email"] == "invited_test@abeni.test"
        assert res_invite.data["role"] == "pharmacist"
        assert AuditEvent.objects.filter(entity_type="tenants.UserInvitation", action="create").exists()

    def test_08_reports_export_csv(self):
        self.client.force_authenticate(user=self.superadmin)

        res_export = self.client.get("/api/v1/platform/reports/export/")
        assert res_export.status_code == 200
        assert res_export["Content-Type"] == "text/csv"
        assert "attachment; filename=" in res_export["Content-Disposition"]
        assert b"Tenant Name,Registration Number,Status" in res_export.content

    def test_09_suspended_tenants_kpi_consistency(self):
        self.client.force_authenticate(user=self.superadmin)

        # Suspend a tenant
        self.tenant.is_active = False
        self.tenant.save()

        # Query analytics API
        res_analytics = self.client.get("/api/v1/platform/analytics/")
        assert res_analytics.status_code == 200
        api_suspended_count = res_analytics.data["totals"]["inactive_tenant_count"]

        # Query DB directly
        db_suspended_count = Tenant.objects.filter(is_active=False).count()

        assert api_suspended_count == db_suspended_count

    def test_10_user_activate_deactivate_and_role_change(self):
        self.client.force_authenticate(user=self.superadmin)

        # 1. Deactivate user
        res_deactivate = self.client.post(f"/api/v1/platform/users/{self.pharmacist.id}/deactivate/")
        assert res_deactivate.status_code == 200
        assert res_deactivate.data["is_active"] is False
        self.pharmacist.refresh_from_db()
        assert self.pharmacist.is_active is False

        # 2. Activate user
        res_activate = self.client.post(f"/api/v1/platform/users/{self.pharmacist.id}/activate/")
        assert res_activate.status_code == 200
        assert res_activate.data["is_active"] is True
        self.pharmacist.refresh_from_db()
        assert self.pharmacist.is_active is True

        # 3. Change role
        res_role = self.client.post(
            f"/api/v1/platform/users/{self.pharmacist.id}/change-role/",
            {"role": "cashier"},
            format="json",
        )
        assert res_role.status_code == 200
        membership = self.pharmacist.memberships.filter(is_active=True).first()
        assert membership.role == "cashier"

    def test_11_user_password_reset_and_setup_flow(self):
        self.client.force_authenticate(user=self.superadmin)

        # 1. Super admin triggers password reset
        res_reset = self.client.post(f"/api/v1/platform/users/{self.pharmacist.id}/reset-password/")
        assert res_reset.status_code == 200
        assert "token" in res_reset.data
        token = res_reset.data["token"]

        # 2. User sets new password using token
        self.client.logout()
        res_setup = self.client.post(
            "/api/v1/auth/setup-password/",
            {"token": token, "new_password": "NewSecretPassword123!"},
            format="json",
        )
        assert res_setup.status_code == 200
        self.pharmacist.refresh_from_db()
        assert self.pharmacist.check_password("NewSecretPassword123!") is True

    def test_12_audit_log_export_and_filtering(self):
        self.client.force_authenticate(user=self.superadmin)

        # Audit logs filter
        res_filter = self.client.get("/api/v1/platform/audit-logs/?action=create")
        assert res_filter.status_code == 200
        assert "results" in res_filter.data

        # Audit logs CSV export
        res_export = self.client.get("/api/v1/platform/audit-logs/export/")
        assert res_export.status_code == 200
        assert res_export["Content-Type"] == "text/csv"
        assert b"Log ID,Created At,Tenant,Actor Email,Action" in res_export.content

    def test_13_super_admin_invitation_promotion_and_email_dispatch(self):
        from django.core import mail
        from apps.accounts.models import User
        from apps.tenants.models import UserInvitation

        self.client.force_authenticate(user=self.superadmin)

        # 1. Invite super_admin
        mail.outbox = []
        res_invite = self.client.post(
            "/api/v1/platform/users/invite/",
            {"email": "new_superadmin@abeni.test", "role": "super_admin"},
            format="json",
        )
        assert res_invite.status_code == 201
        invitation_token = res_invite.data["token"]
        assert len(mail.outbox) == 1
        assert "new_superadmin@abeni.test" in mail.outbox[0].to

        # 2. Resend invitation email
        mail.outbox = []
        invitation_id = res_invite.data["id"]
        res_resend = self.client.post(f"/api/v1/platform/users/invitations/{invitation_id}/resend/")
        assert res_resend.status_code == 200
        assert len(mail.outbox) == 1

        # 3. Setup password for super_admin invitation
        self.client.logout()
        res_setup = self.client.post(
            "/api/v1/auth/setup-password/",
            {"token": invitation_token, "new_password": "SuperSecretPass123!"},
            format="json",
        )
        assert res_setup.status_code == 200

        new_super_user = User.objects.get(email="new_superadmin@abeni.test")
        assert new_super_user.is_superuser is True
        assert new_super_user.is_staff is True
        assert new_super_user.is_active is True

