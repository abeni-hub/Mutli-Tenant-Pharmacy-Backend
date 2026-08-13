import pytest
from rest_framework.test import APIClient

from apps.accounts.models import LoginHistory, PasswordResetToken, User
from apps.tenants.models import Membership, Tenant
from apps.tenants.services import TenantCreateData, TenantService


@pytest.mark.django_db
class TestAuthSystemAllRoles:
    def setup_method(self):
        self.client = APIClient()
        self.roles = [
            ("owner@abeni.test", Membership.Role.OWNER, "Owner", "User"),
            ("cashier@abeni.test", Membership.Role.CASHIER, "Cashier", "User"),
            ("pharmacist@abeni.test", Membership.Role.PHARMACIST, "Pharmacist", "User"),
            ("superadmin@abeni.test", Membership.Role.SUPER_ADMIN, "Super", "Admin"),
        ]

    def test_01_register_all_roles(self):
        for email, _, first_name, last_name in self.roles:
            reg_email = f"reg_{email}"
            response = self.client.post(
                "/api/v1/auth/register/",
                {
                    "email": reg_email,
                    "password": "SecurePassword123!",
                    "first_name": first_name,
                    "last_name": last_name,
                },
                format="json",
            )
            assert response.status_code == 201, response.data
            assert response.data["email"] == reg_email

    def test_02_login_and_token_response(self):
        # Register owner
        self.client.post(
            "/api/v1/auth/register/",
            {
                "email": "owner@abeni.test",
                "password": "SecurePassword123!",
                "first_name": "Owner",
                "last_name": "User",
            },
            format="json",
        )
        # Login
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": "owner@abeni.test", "password": "SecurePassword123!"},
            format="json",
        )
        assert response.status_code == 200
        assert "access" in response.data
        assert "refresh" in response.data
        assert response.data["user"]["email"] == "owner@abeni.test"

        # Check LoginHistory logged
        assert LoginHistory.objects.filter(email_attempted="owner@abeni.test", success=True).exists()

    def test_02b_login_without_trailing_slash(self):
        self.client.post(
            "/api/v1/auth/register/",
            {
                "email": "login-noslash@abeni.test",
                "password": "SecurePassword123!",
                "first_name": "Login",
                "last_name": "NoSlash",
            },
            format="json",
        )

        response = self.client.post(
            "/api/v1/auth/login",
            {"email": "login-noslash@abeni.test", "password": "SecurePassword123!"},
            format="json",
        )

        assert response.status_code == 200
        assert "access" in response.data

    def test_03_token_logout_blacklist(self):
        # Register & Login
        self.client.post(
            "/api/v1/auth/register/",
            {
                "email": "cashier@abeni.test",
                "password": "SecurePassword123!",
                "first_name": "Cashier",
                "last_name": "User",
            },
            format="json",
        )
        login_res = self.client.post(
            "/api/v1/auth/login/",
            {"email": "cashier@abeni.test", "password": "SecurePassword123!"},
            format="json",
        )
        access = login_res.data["access"]
        refresh = login_res.data["refresh"]

        # Logout
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        logout_res = self.client.post(
            "/api/v1/auth/logout/",
            {"refresh": refresh},
            format="json",
        )
        assert logout_res.status_code == 200

        # Attempt to refresh using blacklisted token
        self.client.credentials()
        refresh_res = self.client.post(
            "/api/v1/auth/token/refresh/",
            {"refresh": refresh},
            format="json",
        )
        assert refresh_res.status_code == 401

    def test_04_password_reset_flow(self):
        user = User.objects.create_user(
            email="reset@abeni.test",
            password="OldPassword123!",
            first_name="Reset",
            last_name="User",
        )

        # Request reset
        req_res = self.client.post(
            "/api/v1/auth/password/reset/",
            {"email": "reset@abeni.test"},
            format="json",
        )
        assert req_res.status_code == 200

        token_obj = PasswordResetToken.objects.filter(user=user, is_used=False).first()
        assert token_obj is not None

        # Confirm reset
        confirm_res = self.client.post(
            "/api/v1/auth/password/confirm/",
            {
                "token": str(token_obj.token),
                "new_password": "NewSecurePassword123!",
                "confirm_password": "NewSecurePassword123!",
            },
            format="json",
        )
        assert confirm_res.status_code == 200

        # Try logging in with new password
        login_res = self.client.post(
            "/api/v1/auth/login/",
            {"email": "reset@abeni.test", "password": "NewSecurePassword123!"},
            format="json",
        )
        assert login_res.status_code == 200

    def test_05_tenant_membership_roles(self):
        owner = User.objects.create_user(email="owner2@abeni.test", password="Pass123!Password")
        tenant = TenantService.create_for_owner(owner, TenantCreateData(name="Test Pharmacy"))

        # Verify Owner role
        membership = Membership.objects.get(tenant=tenant, user=owner)
        assert membership.role == Membership.Role.OWNER

        # Create members for all other 6 roles
        other_roles = [
            Membership.Role.CASHIER,
            Membership.Role.PHARMACIST,
            Membership.Role.SUPER_ADMIN,
        ]
        for role in other_roles:
            u = User.objects.create_user(email=f"test_role_{role}@abeni.test", password="Pass123!Password")
            m = Membership.objects.create(tenant=tenant, user=u, role=role)
            assert m.role == role

    def test_06_role_resolution_all_four_personas(self):
        owner = User.objects.create_user(email="owner_test@abeni.test", password="SecurePassword123!")
        pharmacist = User.objects.create_user(email="pharm_test@abeni.test", password="SecurePassword123!")
        cashier = User.objects.create_user(email="cashier_test@abeni.test", password="SecurePassword123!")
        superadmin = User.objects.create_superuser(email="super_test@abeni.test", password="SecurePassword123!")

        tenant = TenantService.create_for_owner(owner, TenantCreateData(name="Main Pharmacy"))
        Membership.objects.create(tenant=tenant, user=pharmacist, role=Membership.Role.PHARMACIST)
        Membership.objects.create(tenant=tenant, user=cashier, role=Membership.Role.CASHIER)

        test_cases = [
            (superadmin, "super_test@abeni.test", "super_admin"),
            (owner, "owner_test@abeni.test", "owner"),
            (pharmacist, "pharm_test@abeni.test", "pharmacist"),
            (cashier, "cashier_test@abeni.test", "cashier"),
        ]

        for user, email, expected_role in test_cases:
            login_res = self.client.post(
                "/api/v1/auth/login/",
                {"email": email, "password": "SecurePassword123!"},
                format="json",
            )
            assert login_res.status_code == 200
            assert login_res.data["user"]["role"] == expected_role

            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_res.data['access']}")
            me_no_header = self.client.get("/api/v1/auth/me/")
            assert me_no_header.status_code == 200
            assert me_no_header.data["role"] == expected_role

            me_with_header = self.client.get(
                "/api/v1/auth/me/",
                HTTP_X_TENANT_ID=str(tenant.id),
            )
            assert me_with_header.status_code == 200
            assert me_with_header.data["role"] == expected_role

    def test_07_tenant_isolation_and_invalid_tenant(self):
        user_a = User.objects.create_user(email="user_a@abeni.test", password="SecurePassword123!")
        user_b = User.objects.create_user(email="user_b@abeni.test", password="SecurePassword123!")

        tenant_a = TenantService.create_for_owner(user_a, TenantCreateData(name="Tenant A"))
        tenant_b = TenantService.create_for_owner(user_b, TenantCreateData(name="Tenant B"))

        # User A logs in and accesses Tenant B header (where User A has NO membership)
        login_res = self.client.post(
            "/api/v1/auth/login/",
            {"email": "user_a@abeni.test", "password": "SecurePassword123!"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_res.data['access']}")

        res = self.client.get("/api/v1/auth/me/", HTTP_X_TENANT_ID=str(tenant_b.id))
        assert res.status_code == 200
        assert res.data["role"] is None  # Does NOT leak role from Tenant A into Tenant B

        # Test inactive membership
        Membership.objects.filter(tenant=tenant_a, user=user_a).update(is_active=False)
        res_inactive = self.client.get("/api/v1/auth/me/", HTTP_X_TENANT_ID=str(tenant_a.id))
        assert res_inactive.status_code == 200
        assert res_inactive.data["role"] is None

