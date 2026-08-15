import pytest
from rest_framework import status
from rest_framework.test import APIClient
from django.utils import timezone
from datetime import timedelta

from apps.accounts.models import User
from apps.subscriptions.models import SubscriptionPlan, TenantSubscription
from apps.tenants.models import Membership, Tenant, Branch


@pytest.fixture
def empty_tenant_owner_client(db):
    """Sets up a brand new empty tenant with an owner account."""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        code=SubscriptionPlan.Code.ENTERPRISE,
        defaults={"name": "Enterprise Plan", "price_monthly": 199, "price_yearly": 1990},
    )
    expires = timezone.now() + timedelta(days=365)

    tenant = Tenant.objects.create(name="Empty Pharmacy", slug="empty-pharmacy", is_active=True)
    TenantSubscription.objects.create(tenant=tenant, plan=plan, status=TenantSubscription.Status.ACTIVE, expires_at=expires)
    Branch.objects.create(tenant=tenant, name="Main Branch", code="EMPTY-01", is_main=True)

    owner = User.objects.create_user(email="empty.owner@test.com", password="Password123!", first_name="Empty", last_name="Owner")
    Membership.objects.create(tenant=tenant, user=owner, role=Membership.Role.OWNER, is_active=True)

    client = APIClient()
    login_resp = client.post("/api/v1/auth/login/", {"email": owner.email, "password": "Password123!"}, format="json")
    token = login_resp.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant.id))

    return {"client": client, "tenant": tenant}


@pytest.mark.django_db
def test_empty_tenant_truth(empty_tenant_owner_client):
    """Verifies that an empty tenant returns clean PostgreSQL zeroes and empty arrays without errors or mock data."""
    client = empty_tenant_owner_client["client"]

    # Dashboard Owner endpoint
    dash_resp = client.get("/api/v1/dashboard/owner/")
    assert dash_resp.status_code == status.HTTP_200_OK
    assert dash_resp.data["recent_activity"] == []

    # Reports Dashboard endpoint
    rep_resp = client.get("/api/v1/reports/dashboard/")
    assert rep_resp.status_code == status.HTTP_200_OK
    today = rep_resp.data["today"]
    inv = rep_resp.data["inventory_summary"]

    assert today["revenue"] == "0.00"
    assert today["sales_count"] == 0
    assert inv["inventory_value"] == "0.00"
    assert inv["active_products_count"] == 0
    assert inv["low_stock_products_count"] == 0
    assert inv["near_expiry_batches_count"] == 0
