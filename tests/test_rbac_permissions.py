import pytest
from rest_framework import status
from rest_framework.test import APIClient
from apps.accounts.models import Permission, PermissionCategory, Role, User
from apps.tenants.models import Tenant
from apps.tenants.services import TenantCreateData, TenantService

@pytest.mark.django_db
class TestSuperAdminRBACSystem:

    def setup_method(self):
        self.superadmin_client = APIClient()
        self.superuser = User.objects.create_superuser(
            email="superadmin_rbac@abeni.test", password="Password123!"
        )
        self.superadmin_client.force_authenticate(user=self.superuser)

        self.owner_client = APIClient()
        self.owner = User.objects.create_user(
            email="owner_rbac@abeni.test", password="Password123!"
        )
        self.tenant = TenantService.create_for_owner(
            self.owner, TenantCreateData(name="RBAC Pharmacy")
        )
        self.owner_client.force_authenticate(user=self.owner)

    def test_01_permission_catalog_endpoint(self):
        """Super Admin can retrieve full permission catalog grouped by category."""
        response = self.superadmin_client.get("/api/v1/platform/permissions/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        # Check tenant management category
        tenants_cat = next((c for c in data if c["key"] == "tenants"), None)
        assert tenants_cat is not None
        assert "permissions" in tenants_cat
        perm_keys = [p["key"] for p in tenants_cat["permissions"]]
        assert "tenants.view" in perm_keys
        assert "tenants.suspend" in perm_keys

    def test_02_list_and_create_custom_role(self):
        """Super Admin can list existing system roles and create a custom role with selected permissions."""
        # 1. List existing roles
        res_list = self.superadmin_client.get("/api/v1/platform/roles/")
        assert res_list.status_code == status.HTTP_200_OK
        roles = res_list.json()
        role_keys = [r["key"] for r in roles]
        assert "super_admin" in role_keys
        assert "owner" in role_keys

        # 2. Create custom role
        payload = {
            "name": "Compliance Inspector",
            "description": "Role for regulatory inspection",
            "scope": "global",
            "permission_keys": ["tenants.view", "security.view", "reports.view"],
        }
        res_create = self.superadmin_client.post("/api/v1/platform/roles/", payload, format="json")
        assert res_create.status_code == status.HTTP_201_CREATED
        new_role = res_create.json()
        assert new_role["name"] == "Compliance Inspector"
        assert new_role["is_system"] is False
        assert set(new_role["permission_keys"]) == {"tenants.view", "security.view", "reports.view"}

    def test_03_update_and_delete_custom_role(self):
        """Super Admin can update permissions of custom roles and delete them."""
        # Create role
        create_res = self.superadmin_client.post("/api/v1/platform/roles/", {
            "name": "Temporary Auditor",
            "scope": "global",
            "permission_keys": ["tenants.view"],
        }, format="json")
        role_id = create_res.json()["id"]

        # Update role permissions
        update_res = self.superadmin_client.put(f"/api/v1/platform/roles/{role_id}/", {
            "name": "Senior Auditor",
            "scope": "global",
            "permission_keys": ["security.view", "health.view"],
        }, format="json")
        assert update_res.status_code == status.HTTP_200_OK
        updated = update_res.json()
        assert updated["name"] == "Senior Auditor"
        assert set(updated["permission_keys"]) == {"security.view", "health.view"}

        # Delete role
        del_res = self.superadmin_client.delete(f"/api/v1/platform/roles/{role_id}/")
        assert del_res.status_code == status.HTTP_204_NO_CONTENT

    def test_04_system_role_protection(self):
        """System roles cannot be deleted or edited."""
        super_admin_role = Role.objects.get(key="super_admin")

        # Attempt to delete
        del_res = self.superadmin_client.delete(f"/api/v1/platform/roles/{super_admin_role.id}/")
        assert del_res.status_code == status.HTTP_400_BAD_REQUEST

        # Attempt to edit
        edit_res = self.superadmin_client.put(f"/api/v1/platform/roles/{super_admin_role.id}/", {
            "name": "Modified Super Admin",
            "permission_keys": [],
        }, format="json")
        assert edit_res.status_code == status.HTTP_400_BAD_REQUEST

    def test_05_non_super_admin_forbidden(self):
        """Non-Super Admin users are forbidden from viewing or altering RBAC catalog."""
        res_perms = self.owner_client.get("/api/v1/platform/permissions/")
        assert res_perms.status_code == status.HTTP_403_FORBIDDEN

        res_roles = self.owner_client.get("/api/v1/platform/roles/")
        assert res_roles.status_code == status.HTTP_403_FORBIDDEN
