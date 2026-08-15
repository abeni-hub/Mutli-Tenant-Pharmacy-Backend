import pytest
from rest_framework import status
from rest_framework.test import APIClient
from django.core.management import call_command

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.inventory.models import StockBatch
from apps.purchases.models import PurchaseOrder, Supplier
from apps.sales.models import Sale
from apps.tenants.models import Membership, Tenant


@pytest.mark.django_db
def test_seed_owner_demo_idempotency_and_completeness():
    """Verify that seed_owner_demo runs idempotently and populates all required entities."""
    # Run 1
    call_command("seed_owner_demo")
    # Run 2
    call_command("seed_owner_demo")

    owner = User.objects.get(email="owner@abeni.test")
    membership = Membership.objects.get(user=owner, is_active=True)
    tenant = membership.tenant

    # Users
    assert User.objects.filter(email="pharmacist@abeni.test").exists()
    assert User.objects.filter(email="cashier@abeni.test").exists()

    # Products & Categories
    products = Product.unscoped.filter(tenant=tenant)
    assert products.count() >= 10
    categories = set(products.values_list("category", flat=True))
    assert "Antibiotics" in categories
    assert "Analgesics" in categories
    assert "Vitamins" in categories
    assert "Antihypertensives" in categories
    assert "Diabetes" in categories
    assert "Gastrointestinal" in categories

    # Batches
    batches = StockBatch.unscoped.filter(tenant=tenant)
    assert batches.count() >= 5

    # Sales & Purchases
    sales = Sale.unscoped.filter(tenant=tenant)
    assert sales.exists()

    purchases = PurchaseOrder.unscoped.filter(tenant=tenant)
    assert purchases.exists()

    suppliers = Supplier.unscoped.filter(tenant=tenant)
    assert suppliers.exists()


@pytest.mark.django_db
def test_dashboard_api_returns_seeded_data():
    """Verify that Owner Dashboard APIs return real PostgreSQL metrics from seeded demo data."""
    call_command("seed_owner_demo")

    owner = User.objects.get(email="owner@abeni.test")
    membership = Membership.objects.get(user=owner, is_active=True)
    tenant_id = str(membership.tenant_id)

    client = APIClient()
    login_resp = client.post("/api/v1/auth/login/", {"email": "owner@abeni.test", "password": "SecurePassword123!"}, format="json")
    token = login_resp.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=tenant_id)

    # GET /api/v1/reports/dashboard/
    resp = client.get("/api/v1/reports/dashboard/")
    assert resp.status_code == status.HTTP_200_OK

    inv = resp.data["inventory_summary"]
    assert inv["active_products_count"] >= 10
    assert float(inv["inventory_value"]) > 0
    assert inv["supplier_count"] >= 3
