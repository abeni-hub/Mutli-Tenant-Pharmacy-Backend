import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.inventory.models import StockBatch
from apps.purchases.models import Supplier
from apps.sales.models import Sale
from apps.subscriptions.models import SubscriptionPlan, TenantSubscription
from apps.tenants.models import Membership, Tenant


@pytest.fixture
def two_tenants_setup(db):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        code=SubscriptionPlan.Code.ENTERPRISE,
        defaults={"name": "Enterprise", "price_monthly": 199, "price_yearly": 1990},
    )

    from django.utils import timezone
    from datetime import timedelta
    expires = timezone.now() + timedelta(days=365)

    # Tenant A & Owner A
    tenant_a = Tenant.objects.create(name="Tenant Alpha", slug="tenant-alpha", is_active=True)
    TenantSubscription.objects.create(tenant=tenant_a, plan=plan, status=TenantSubscription.Status.ACTIVE, expires_at=expires)
    owner_a = User.objects.create_user(email="owner.a@test.com", password="Password123!", first_name="Owner", last_name="Alpha")
    Membership.objects.create(tenant=tenant_a, user=owner_a, role=Membership.Role.OWNER, is_active=True)

    prod_a = Product.objects.create(tenant=tenant_a, name="Alpha Pill 500mg", sku="ALPHA-500", is_active=True)
    sup_a = Supplier.objects.create(tenant=tenant_a, company_name="Alpha Supplier", code="SUP-ALPHA")

    # Tenant B & Owner B
    tenant_b = Tenant.objects.create(name="Tenant Beta", slug="tenant-beta", is_active=True)
    TenantSubscription.objects.create(tenant=tenant_b, plan=plan, status=TenantSubscription.Status.ACTIVE, expires_at=expires)
    owner_b = User.objects.create_user(email="owner.b@test.com", password="Password123!", first_name="Owner", last_name="Beta")
    Membership.objects.create(tenant=tenant_b, user=owner_b, role=Membership.Role.OWNER, is_active=True)

    prod_b = Product.objects.create(tenant=tenant_b, name="Beta Syrup 100ml", sku="BETA-100", is_active=True)
    sup_b = Supplier.objects.create(tenant=tenant_b, company_name="Beta Supplier", code="SUP-BETA")

    return {
        "tenant_a": tenant_a, "owner_a": owner_a, "prod_a": prod_a, "sup_a": sup_a,
        "tenant_b": tenant_b, "owner_b": owner_b, "prod_b": prod_b, "sup_b": sup_b,
    }


@pytest.mark.django_db
def test_owner_cannot_access_other_tenant_header(two_tenants_setup):
    client = APIClient()
    owner_a = two_tenants_setup["owner_a"]
    tenant_b = two_tenants_setup["tenant_b"]

    # Login Owner A
    login_resp = client.post("/api/v1/auth/login/", {"email": owner_a.email, "password": "Password123!"}, format="json")
    token = login_resp.data["access"]

    # Try to make request with Tenant B's X-Tenant-ID header
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant_b.id))

    # Expect Forbidden because Owner A is not a member of Tenant B
    resp = client.get("/api/v1/products/")
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_owner_products_isolated(two_tenants_setup):
    client = APIClient()
    owner_a = two_tenants_setup["owner_a"]
    tenant_a = two_tenants_setup["tenant_a"]

    login_resp = client.post("/api/v1/auth/login/", {"email": owner_a.email, "password": "Password123!"}, format="json")
    token = login_resp.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant_a.id))

    resp = client.get("/api/v1/products/")
    assert resp.status_code == status.HTTP_200_OK
    items = resp.data["results"] if isinstance(resp.data, dict) and "results" in resp.data else resp.data
    skus = [p["sku"] for p in items]
    assert "ALPHA-500" in skus
    assert "BETA-100" not in skus


@pytest.mark.django_db
def test_owner_dashboard_stats_isolated(two_tenants_setup):
    client = APIClient()
    owner_a = two_tenants_setup["owner_a"]
    tenant_a = two_tenants_setup["tenant_a"]

    login_resp = client.post("/api/v1/auth/login/", {"email": owner_a.email, "password": "Password123!"}, format="json")
    token = login_resp.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant_a.id))

    resp = client.get("/api/v1/dashboard/owner/")
    assert resp.status_code == status.HTTP_200_OK
