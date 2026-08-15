import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.subscriptions.models import SubscriptionPlan, TenantSubscription
from apps.tenants.models import Membership, Tenant


@pytest.fixture
def owner_setup(db):
    """Fixture providing a seeded Owner, Tenant, and APIClient."""
    tenant = Tenant.objects.create(name="Test Pharmacy", slug="test-pharmacy", is_active=True)
    plan, _ = SubscriptionPlan.objects.get_or_create(
        code=SubscriptionPlan.Code.PROFESSIONAL,
        defaults={"name": "Professional", "price_monthly": 99, "price_yearly": 990},
    )
    from django.utils import timezone
    from datetime import timedelta
    TenantSubscription.objects.create(tenant=tenant, plan=plan, status=TenantSubscription.Status.ACTIVE, expires_at=timezone.now() + timedelta(days=365))

    user = User.objects.create_user(email="owner.test@abeni.test", password="SecurePassword123!", first_name="Test", last_name="Owner")
    Membership.objects.create(tenant=tenant, user=user, role=Membership.Role.OWNER, is_active=True)

    client = APIClient()
    return {"tenant": tenant, "user": user, "client": client}


@pytest.mark.django_db
def test_owner_login_and_me_endpoint(owner_setup):
    client = owner_setup["client"]
    user = owner_setup["user"]
    tenant = owner_setup["tenant"]

    # 1. Login
    login_resp = client.post("/api/v1/auth/login/", {"email": user.email, "password": "SecurePassword123!"}, format="json")
    assert login_resp.status_code == status.HTTP_200_OK
    assert "access" in login_resp.data

    token = login_resp.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant.id))

    # 2. Auth /me
    me_resp = client.get("/api/v1/auth/me/")
    assert me_resp.status_code == status.HTTP_200_OK
    assert me_resp.data["email"] == user.email
    assert me_resp.data["role"] == "owner"


@pytest.mark.django_db
def test_owner_dashboard_api(owner_setup):
    client = owner_setup["client"]
    user = owner_setup["user"]
    tenant = owner_setup["tenant"]

    login_resp = client.post("/api/v1/auth/login/", {"email": user.email, "password": "SecurePassword123!"}, format="json")
    token = login_resp.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant.id))

    # GET /api/v1/dashboard/owner/
    resp = client.get("/api/v1/dashboard/owner/")
    assert resp.status_code == status.HTTP_200_OK
    assert "kpis" in resp.data
    assert "recent_activities" in resp.data or "recent_activity" in resp.data


@pytest.mark.django_db
def test_owner_reports_dashboard_and_charts(owner_setup):
    client = owner_setup["client"]
    user = owner_setup["user"]
    tenant = owner_setup["tenant"]

    login_resp = client.post("/api/v1/auth/login/", {"email": user.email, "password": "SecurePassword123!"}, format="json")
    token = login_resp.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant.id))

    # GET /api/v1/reports/dashboard/
    rep_resp = client.get("/api/v1/reports/dashboard/")
    assert rep_resp.status_code == status.HTTP_200_OK
    assert "today" in rep_resp.data
    assert "this_month" in rep_resp.data
    assert "inventory_summary" in rep_resp.data

    inv = rep_resp.data["inventory_summary"]
    assert "low_stock_products_count" in inv or "low_stock_products" in inv
    assert "near_expiry_batches_count" in inv or "near_expiry_batches" in inv

    # GET /api/v1/reports/charts/
    charts_resp = client.get("/api/v1/reports/charts/?period=monthly")
    assert charts_resp.status_code == status.HTTP_200_OK
    assert "datasets" in charts_resp.data or "chart_type" in charts_resp.data or "period" in charts_resp.data


@pytest.mark.django_db
def test_owner_blocked_from_superadmin_endpoints(owner_setup):
    client = owner_setup["client"]
    user = owner_setup["user"]
    tenant = owner_setup["tenant"]

    login_resp = client.post("/api/v1/auth/login/", {"email": user.email, "password": "SecurePassword123!"}, format="json")
    token = login_resp.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant.id))

    # Attempting to access Super Admin platform tenant management endpoint
    resp = client.get("/api/v1/platform/tenants/")
    assert resp.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED]
