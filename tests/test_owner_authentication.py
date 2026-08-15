import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.tenants.models import Membership, Tenant


@pytest.mark.django_db
def test_owner_authentication_phase2():
    """Verify Phase 2 Owner Authentication criteria strictly against seeded owner data."""
    from django.core.management import call_command
    call_command("seed_owner_demo")

    client = APIClient()

    # 1. Login with owner@abeni.test / SecurePassword123!
    login_payload = {
        "email": "owner@abeni.test",
        "password": "SecurePassword123!",
    }
    login_resp = client.post("/api/v1/auth/login/", login_payload, format="json")
    assert login_resp.status_code == status.HTTP_200_OK, f"Login failed: {login_resp.data}"

    # Verify access and refresh tokens exist
    assert "access" in login_resp.data, "Login response missing 'access' token"
    assert "refresh" in login_resp.data, "Login response missing 'refresh' token"

    access_token = login_resp.data["access"]
    refresh_token = login_resp.data["refresh"]

    assert len(access_token) > 20
    assert len(refresh_token) > 20

    # 2. Query GET /api/v1/auth/me/ without header to retrieve tenant_id
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    me_resp_init = client.get("/api/v1/auth/me/")
    assert me_resp_init.status_code == status.HTTP_200_OK

    data_init = me_resp_init.data
    assert data_init["email"] == "owner@abeni.test"
    assert data_init["role"] == "owner", f"Expected backend role 'owner', got '{data_init.get('role')}'"
    assert "tenant_id" in data_init and data_init["tenant_id"] is not None

    owner_tenant_id = data_init["tenant_id"]

    # 3. Query with X-Tenant-ID header attached
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {access_token}",
        HTTP_X_TENANT_ID=str(owner_tenant_id),
    )

    me_resp = client.get("/api/v1/auth/me/")
    assert me_resp.status_code == status.HTTP_200_OK

    me_data = me_resp.data
    assert me_data["email"] == "owner@abeni.test"
    assert me_data["first_name"] != ""
    assert me_data["last_name"] != ""
    assert me_data["role"] == "owner"
    assert str(me_data["tenant_id"]) == str(owner_tenant_id)

    # 4. Verify tenant-scoped endpoints (e.g. Products / Dashboard) accept X-Tenant-ID
    dash_resp = client.get("/api/v1/dashboard/owner/")
    assert dash_resp.status_code == status.HTTP_200_OK
    assert "kpis" in dash_resp.data


@pytest.mark.django_db
def test_unknown_role_rejection():
    """Verify that roles other than owner/pharmacist/cashier/super_admin cannot spoof owner."""
    user = User.objects.create_user(email="unknown@test.com", password="Password123!")
    # Create invalid role membership
    tenant = Tenant.objects.create(name="Obsolete Tenant", slug="obsolete-tenant")
    Membership.objects.create(tenant=tenant, user=user, role="obsolete_role", is_active=True)

    client = APIClient()
    login_resp = client.post("/api/v1/auth/login/", {"email": user.email, "password": "Password123!"}, format="json")
    assert login_resp.status_code == status.HTTP_200_OK

    token = login_resp.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant.id))

    me_resp = client.get("/api/v1/auth/me/")
    assert me_resp.status_code == status.HTTP_200_OK
    # Backend role must be obsolete_role (or null/unrecognized), NOT owner
    assert me_resp.data["role"] != "owner"
