import pytest
from rest_framework.test import APIClient
from apps.accounts.models import User, Role, Permission
from apps.tenants.models import Tenant, Membership

@pytest.mark.django_db
class TestTenantProvisioningAndRBAC:
    @pytest.fixture(autouse=True)
    def setup_data(self):
        self.client = APIClient()
        self.superadmin = User.objects.create_superuser(
            email="superadmin_test_prov@abeni.test",
            password="SuperPassword123!",
            first_name="Global",
            last_name="Admin",
        )

    def test_superadmin_tenant_provisioning_temporary_password(self):
        self.client.force_authenticate(user=self.superadmin)
        res = self.client.post(
            "/api/v1/platform/tenants/",
            {
                "name": "Provisioned Express Pharmacy",
                "registration_number": "REG-EXPRESS-101",
                "owner_first_name": "Express",
                "owner_last_name": "Owner",
                "owner_email": "express_owner@abeni.test",
                "plan_code": "enterprise",
            },
            format="json",
        )
        assert res.status_code == 201
        data = res.json()

        assert "id" in data
        assert data["admin_email"] == "express_owner@abeni.test"
        assert "temporary_password" in data
        assert data["must_change_password"] is True

        owner_user = User.objects.get(email="express_owner@abeni.test")
        assert owner_user.must_change_password is True

    def test_mailhog_email_dispatch_on_tenant_creation(self):
        from django.core import mail
        self.client.force_authenticate(user=self.superadmin)
        res = self.client.post(
            "/api/v1/platform/tenants/",
            {
                "name": "MailHog Test Pharmacy",
                "owner_first_name": "MailHog",
                "owner_last_name": "Owner",
                "owner_email": "mailhog_owner@abeni.test",
            },
            format="json",
        )
        assert res.status_code == 201
        assert len(mail.outbox) == 1
        sent_email = mail.outbox[0]
        assert "mailhog_owner@abeni.test" in sent_email.to
        assert "Welcome to MeridianRx" in sent_email.subject
        assert res.json()["temporary_password"] in sent_email.body

    def test_first_login_password_change_flow(self):
        self.client.force_authenticate(user=self.superadmin)
        res_create = self.client.post(
            "/api/v1/platform/tenants/",
            {
                "name": "First Login Test Tenant",
                "owner_first_name": "First",
                "owner_last_name": "Login",
                "owner_email": "first_login_owner@abeni.test",
            },
            format="json",
        )
        temp_pass = res_create.json()["temporary_password"]

        # Log in with temporary password
        client_owner = APIClient()
        login_res = client_owner.post(
            "/api/v1/auth/login/",
            {"email": "first_login_owner@abeni.test", "password": temp_pass},
            format="json",
        )
        assert login_res.status_code == 200
        owner_data = login_res.json()
        assert owner_data["user"]["must_change_password"] is True
        access_token = owner_data["access"]

        # Execute password change
        client_owner.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        change_res = client_owner.post(
            "/api/v1/auth/change-password/",
            {
                "current_password": temp_pass,
                "new_password": "NewPermanentPass123!",
                "confirm_password": "NewPermanentPass123!",
            },
            format="json",
        )
        assert change_res.status_code == 200
        assert change_res.json()["user"]["must_change_password"] is False

        # Verify database state
        owner_user = User.objects.get(email="first_login_owner@abeni.test")
        assert owner_user.must_change_password is False
        assert owner_user.check_password("NewPermanentPass123!") is True

    def test_tenant_admin_cannot_create_global_role(self):
        # Create tenant owner
        tenant = Tenant.objects.create(name="Scope Restriction Tenant", slug="scope-rest-tenant")
        owner_user = User.objects.create_user(
            email="tenant_scope_owner@abeni.test", password="Password123!"
        )
        Membership.objects.create(tenant=tenant, user=owner_user, role=Membership.Role.OWNER)

        client = APIClient()
        client.force_authenticate(user=owner_user)

        res = client.post(
            "/api/v1/roles/",
            {
                "name": "Attempted Global Role",
                "description": "Should be scoped to tenant",
                "scope": "global",
            },
            HTTP_X_TENANT_ID=str(tenant.id),
            format="json",
        )
        assert res.status_code == 201
        created_role = Role.objects.get(id=res.json()["id"])
        # Non-superadmin cannot create global role; backend forces scope to TENANT
        assert created_role.scope == Role.Scope.TENANT
        assert created_role.tenant_id == tenant.id
