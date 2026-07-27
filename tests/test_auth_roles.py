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
            ("manager@abeni.test", Membership.Role.MANAGER, "Manager", "User"),
            ("cashier@abeni.test", Membership.Role.CASHIER, "Cashier", "User"),
            ("inventory@abeni.test", Membership.Role.INVENTORY_MANAGER, "Inventory", "Manager"),
            ("pharmacist@abeni.test", Membership.Role.PHARMACIST, "Pharmacist", "User"),
            ("accountant@abeni.test", Membership.Role.ACCOUNTANT, "Accountant", "User"),
            ("superadmin@abeni.test", Membership.Role.SUPER_ADMIN, "Super", "Admin"),
        ]

    def test_01_register_all_roles(self):
        for email, _, first_name, last_name in self.roles:
            response = self.client.post(
                "/api/v1/auth/register/",
                {
                    "email": email,
                    "password": "SecurePassword123!",
                    "first_name": first_name,
                    "last_name": last_name,
                },
                format="json",
            )
            assert response.status_code == 201, response.data
            assert response.data["email"] == email

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
            Membership.Role.MANAGER,
            Membership.Role.CASHIER,
            Membership.Role.INVENTORY_MANAGER,
            Membership.Role.PHARMACIST,
            Membership.Role.ACCOUNTANT,
            Membership.Role.SUPER_ADMIN,
        ]
        for role in other_roles:
            u = User.objects.create_user(email=f"{role}@abeni.test", password="Pass123!Password")
            m = Membership.objects.create(tenant=tenant, user=u, role=role)
            assert m.role == role
