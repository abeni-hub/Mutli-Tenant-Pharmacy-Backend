import pytest
from rest_framework.test import APIClient
from apps.accounts.models import User, Role, Permission, PermissionCategory
from apps.tenants.models import Tenant, Membership

def get_results(res):
    data = res.json()
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    return data

@pytest.mark.django_db
class TestRBACScopeAndIsolation:
    @pytest.fixture(autouse=True)
    def setup_data(self):
        self.client = APIClient()

        # Seed RBAC Permissions
        from django.core.management import call_command
        call_command("seed_rbac_permissions")

        # Create Global Super Admin
        self.superadmin = User.objects.create_superuser(
            email="superadmin_test@abeni.test",
            password="SuperPassword123!",
            first_name="Global",
            last_name="SuperAdmin",
        )

        # Create Tenant A & Tenant A Owner
        self.tenant_a = Tenant.objects.create(name="Tenant Alpha", slug="tenant-alpha", registration_number="REG-ALPHA-01")
        self.owner_a = User.objects.create_user(
            email="owner_a@alpha.test",
            password="Password123!",
            first_name="Owner",
            last_name="Alpha",
        )
        Membership.objects.create(user=self.owner_a, tenant=self.tenant_a, role=Membership.Role.OWNER, is_active=True)

        # Create Tenant B & Tenant B Owner
        self.tenant_b = Tenant.objects.create(name="Tenant Beta", slug="tenant-beta", registration_number="REG-BETA-02")
        self.owner_b = User.objects.create_user(
            email="owner_b@beta.test",
            password="Password123!",
            first_name="Owner",
            last_name="Beta",
        )
        Membership.objects.create(user=self.owner_b, tenant=self.tenant_b, role=Membership.Role.OWNER, is_active=True)

    def test_1_tenant_a_creates_custom_role(self):
        """TEST 1: Tenant A creates 'Accountant' -> scope=TENANT, tenant_id=A"""
        self.client.force_authenticate(user=self.owner_a)
        res = self.client.post(
            "/api/v1/roles/",
            {
                "name": "Accountant",
                "description": "Tenant A Accountant Role",
                "permission_keys": ["sales.view", "reports.view"],
            },
            HTTP_X_TENANT_ID=str(self.tenant_a.id),
            format="json",
        )
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "Accountant"
        assert data["scope"] == "tenant"

        role_obj = Role.objects.get(id=data["id"])
        assert role_obj.scope == Role.Scope.TENANT
        assert role_obj.tenant_id == self.tenant_a.id

    def test_2_and_3_tenant_role_isolation(self):
        """TEST 2 & 3: Tenant A sees Tenant A roles; Tenant B does NOT see Tenant A roles."""
        # Tenant A creates "Sales Lead"
        self.client.force_authenticate(user=self.owner_a)
        res_create = self.client.post(
            "/api/v1/roles/",
            {"name": "Sales Lead", "permission_keys": ["sales.view"]},
            HTTP_X_TENANT_ID=str(self.tenant_a.id),
            format="json",
        )
        assert res_create.status_code == 201

        # TEST 2: Tenant A requests roles
        res_a = self.client.get("/api/v1/roles/", HTTP_X_TENANT_ID=str(self.tenant_a.id))
        assert res_a.status_code == 200
        roles_a = [r["name"] for r in get_results(res_a)]
        assert "Sales Lead" in roles_a
        assert "Super Admin" not in roles_a

        # TEST 3: Tenant B requests roles
        self.client.force_authenticate(user=self.owner_b)
        res_b = self.client.get("/api/v1/roles/", HTTP_X_TENANT_ID=str(self.tenant_b.id))
        assert res_b.status_code == 200
        roles_b = [r["name"] for r in get_results(res_b)]
        assert "Sales Lead" not in roles_b

    def test_4_global_owner_role_list_separates_tenant_roles(self):
        """TEST 4: Global Owner opens global roles -> Tenant A custom roles do NOT appear in global role list."""
        self.client.force_authenticate(user=self.owner_a)
        self.client.post(
            "/api/v1/roles/",
            {"name": "Custom Tenant A Role", "permission_keys": ["products.view"]},
            HTTP_X_TENANT_ID=str(self.tenant_a.id),
            format="json",
        )

        self.client.force_authenticate(user=self.superadmin)
        res_global = self.client.get("/api/v1/roles/")
        assert res_global.status_code == 200
        global_role_names = [r["name"] for r in get_results(res_global)]
        assert "Custom Tenant A Role" not in global_role_names

    def test_5_and_6_cross_tenant_and_global_modification_blocked(self):
        """TEST 5 & 6: Tenant A cannot access/modify Tenant B or Global roles."""
        # Create role in Tenant B
        role_b = Role.objects.create(
            key="custom_role_b",
            name="Tenant B Role",
            scope=Role.Scope.TENANT,
            tenant=self.tenant_b,
        )
        global_role = Role.objects.get(key="super_admin")

        self.client.force_authenticate(user=self.owner_a)

        # TEST 5: Tenant A attempts to update Tenant B role -> 404 or 403
        res_mod_b = self.client.put(
            f"/api/v1/roles/{role_b.id}/",
            {"name": "Hacked Role B", "permission_keys": []},
            HTTP_X_TENANT_ID=str(self.tenant_a.id),
            format="json",
        )
        assert res_mod_b.status_code in [403, 404]

        # TEST 6: Tenant A attempts to modify Global role -> 403 or 404
        res_mod_g = self.client.put(
            f"/api/v1/roles/{global_role.id}/",
            {"name": "Hacked Super Admin", "permission_keys": []},
            HTTP_X_TENANT_ID=str(self.tenant_a.id),
            format="json",
        )
        assert res_mod_g.status_code in [403, 404]

    def test_7_and_10_submitting_global_permission_rejected(self):
        """TEST 7 & 10: Tenant A attempting to assign a GLOBAL scope permission -> 403 Forbidden."""
        self.client.force_authenticate(user=self.owner_a)
        res = self.client.post(
            "/api/v1/roles/",
            {
                "name": "Malicious Role",
                "permission_keys": ["tenants.create", "platform.system_health"],
            },
            HTTP_X_TENANT_ID=str(self.tenant_a.id),
            format="json",
        )
        assert res.status_code == 403
        data = res.json()
        detail_text = data.get("detail") or data.get("error", {}).get("detail", "")
        assert "Permission Denied" in detail_text

    def test_8_and_9_permission_visibility_by_scope(self):
        """TEST 8 & 9: Tenant A sees only tenant permissions; global-only categories are hidden."""
        self.client.force_authenticate(user=self.owner_a)
        res = self.client.get("/api/v1/permissions/", HTTP_X_TENANT_ID=str(self.tenant_a.id))
        assert res.status_code == 200
        categories = get_results(res)

        for cat in categories:
            for p in cat.get("permissions", []):
                assert p["scope"] == "tenant"

    def test_11_and_12_global_owner_explicit_context(self):
        """TEST 11 & 12: Global Owner can access global roles and inspect tenant roles with explicit context."""
        self.client.force_authenticate(user=self.superadmin)

        # TEST 11: Global Owner gets global roles
        res_g = self.client.get("/api/v1/roles/")
        assert res_g.status_code == 200

        # TEST 12: Global Owner requests Tenant A roles with explicit query param
        res_t = self.client.get(f"/api/v1/roles/?tenant_id={self.tenant_a.id}")
        assert res_t.status_code == 200
