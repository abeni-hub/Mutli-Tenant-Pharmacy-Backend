from decimal import Decimal
from datetime import timedelta
import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.inventory.models import StockBatch
from apps.purchases.models import Supplier, PurchaseOrder
from apps.sales.models import Sale, SaleItem
from apps.subscriptions.models import SubscriptionPlan, TenantSubscription
from apps.tenants.models import Membership, Tenant, Branch


@pytest.fixture
def isolation_environment(db):
    """Sets up two completely distinct tenants with full business records."""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        code=SubscriptionPlan.Code.ENTERPRISE,
        defaults={"name": "Enterprise Plan", "price_monthly": 199, "price_yearly": 1990},
    )
    expires = timezone.now() + timedelta(days=365)

    # ── TENANT A ─────────────────────────────────────────────────────────────
    tenant_a = Tenant.objects.create(name="Pharmacy Alpha", slug="pharmacy-alpha", is_active=True)
    TenantSubscription.objects.create(tenant=tenant_a, plan=plan, status=TenantSubscription.Status.ACTIVE, expires_at=expires)
    branch_a = Branch.objects.create(tenant=tenant_a, name="Alpha Main", code="ALPHA-01", is_main=True)

    owner_a = User.objects.create_user(email="owner.alpha@test.com", password="Password123!", first_name="Alpha", last_name="Owner")
    Membership.objects.create(tenant=tenant_a, user=owner_a, role=Membership.Role.OWNER, is_active=True)

    prod_a = Product.objects.create(tenant=tenant_a, name="Amoxicillin 500mg", sku="AMX-ALPHA", is_active=True)
    sup_a = Supplier.objects.create(tenant=tenant_a, company_name="Alpha Pharma Ltd", code="SUP-A")
    batch_a = StockBatch.objects.create(
        tenant=tenant_a, product=prod_a, batch_number="B-ALPHA-01", quantity=100,
        expiry_date=timezone.now().date() + timedelta(days=200), unit_price=Decimal("5.00"), selling_price=Decimal("10.00"),
    )
    po_a = PurchaseOrder.objects.create(
        tenant=tenant_a, po_number="PO-ALPHA-01", supplier=sup_a, branch=branch_a.name,
        status=PurchaseOrder.Status.APPROVED, total=Decimal("500.00"),
    )
    sale_a = Sale.objects.create(
        tenant=tenant_a, invoice_number="INV-ALPHA-01", branch=branch_a.name, cashier=owner_a,
        customer_name="Customer Alpha", customer_phone="+111111111", subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"), status=Sale.Status.COMPLETED,
    )
    SaleItem.objects.create(
        tenant=tenant_a, sale=sale_a, product=prod_a, batch=batch_a, quantity=10,
        unit_cost_price=Decimal("5.00"), unit_selling_price=Decimal("10.00"),
        total_cost=Decimal("50.00"), total_price=Decimal("100.00"), profit=Decimal("50.00"),
    )

    # ── TENANT B ─────────────────────────────────────────────────────────────
    tenant_b = Tenant.objects.create(name="Pharmacy Beta", slug="pharmacy-beta", is_active=True)
    TenantSubscription.objects.create(tenant=tenant_b, plan=plan, status=TenantSubscription.Status.ACTIVE, expires_at=expires)
    branch_b = Branch.objects.create(tenant=tenant_b, name="Beta Main", code="BETA-01", is_main=True)

    owner_b = User.objects.create_user(email="owner.beta@test.com", password="Password123!", first_name="Beta", last_name="Owner")
    Membership.objects.create(tenant=tenant_b, user=owner_b, role=Membership.Role.OWNER, is_active=True)

    prod_b = Product.objects.create(tenant=tenant_b, name="Ibuprofen 400mg", sku="IBU-BETA", is_active=True)
    sup_b = Supplier.objects.create(tenant=tenant_b, company_name="Beta Meds Supply", code="SUP-B")
    batch_b = StockBatch.objects.create(
        tenant=tenant_b, product=prod_b, batch_number="B-BETA-01", quantity=200,
        expiry_date=timezone.now().date() + timedelta(days=300), unit_price=Decimal("3.00"), selling_price=Decimal("7.00"),
    )
    po_b = PurchaseOrder.objects.create(
        tenant=tenant_b, po_number="PO-BETA-01", supplier=sup_b, branch=branch_b.name,
        status=PurchaseOrder.Status.APPROVED, total=Decimal("600.00"),
    )
    sale_b = Sale.objects.create(
        tenant=tenant_b, invoice_number="INV-BETA-01", branch=branch_b.name, cashier=owner_b,
        customer_name="Customer Beta", customer_phone="+222222222", subtotal=Decimal("200.00"),
        total_amount=Decimal("200.00"), status=Sale.Status.COMPLETED,
    )
    SaleItem.objects.create(
        tenant=tenant_b, sale=sale_b, product=prod_b, batch=batch_b, quantity=20,
        unit_cost_price=Decimal("3.00"), unit_selling_price=Decimal("7.00"),
        total_cost=Decimal("60.00"), total_price=Decimal("140.00"), profit=Decimal("80.00"),
    )

    return {
        "tenant_a": tenant_a, "owner_a": owner_a, "prod_a": prod_a, "sup_a": sup_a, "po_a": po_a, "sale_a": sale_a,
        "tenant_b": tenant_b, "owner_b": owner_b, "prod_b": prod_b, "sup_b": sup_b, "po_b": po_b, "sale_b": sale_b,
    }


@pytest.mark.django_db
def test_owner_a_blocked_from_tenant_b_header(isolation_environment):
    """Owner A cannot send Tenant B's X-Tenant-ID header to access Tenant B endpoints."""
    client = APIClient()
    owner_a = isolation_environment["owner_a"]
    tenant_b = isolation_environment["tenant_b"]

    login_resp = client.post("/api/v1/auth/login/", {"email": owner_a.email, "password": "Password123!"}, format="json")
    token = login_resp.data["access"]

    # Header set to Tenant B
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant_b.id))

    endpoints = [
        "/api/v1/products/",
        "/api/v1/inventory/batches/",
        "/api/v1/sales/",
        "/api/v1/suppliers/",
        "/api/v1/purchases/",
        "/api/v1/reports/dashboard/",
        "/api/v1/dashboard/owner/",
    ]

    for ep in endpoints:
        resp = client.get(ep)
        assert resp.status_code == status.HTTP_403_FORBIDDEN, f"Endpoint {ep} allowed cross-tenant access!"


@pytest.mark.django_db
def test_owner_a_sees_only_tenant_a_data(isolation_environment):
    """Owner A with Tenant A's X-Tenant-ID header sees only Tenant A records across all models."""
    client = APIClient()
    owner_a = isolation_environment["owner_a"]
    tenant_a = isolation_environment["tenant_a"]

    login_resp = client.post("/api/v1/auth/login/", {"email": owner_a.email, "password": "Password123!"}, format="json")
    token = login_resp.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant_a.id))

    # 1. Products
    p_resp = client.get("/api/v1/products/")
    assert p_resp.status_code == status.HTTP_200_OK
    p_items = p_resp.data["results"] if isinstance(p_resp.data, dict) and "results" in p_resp.data else p_resp.data
    skus = [p["sku"] for p in p_items]
    assert "AMX-ALPHA" in skus
    assert "IBU-BETA" not in skus

    # 2. Inventory Batches
    b_resp = client.get("/api/v1/inventory/batches/")
    assert b_resp.status_code == status.HTTP_200_OK
    b_items = b_resp.data["results"] if isinstance(b_resp.data, dict) and "results" in b_resp.data else b_resp.data
    batch_nums = [b["batch_number"] for b in b_items]
    assert "B-ALPHA-01" in batch_nums
    assert "B-BETA-01" not in batch_nums

    # 3. Sales
    s_resp = client.get("/api/v1/sales/")
    assert s_resp.status_code == status.HTTP_200_OK
    s_items = s_resp.data["results"] if isinstance(s_resp.data, dict) and "results" in s_resp.data else s_resp.data
    invoices = [s["invoice_number"] for s in s_items]
    assert "INV-ALPHA-01" in invoices
    assert "INV-BETA-01" not in invoices

    # 4. Suppliers
    sup_resp = client.get("/api/v1/suppliers/")
    assert sup_resp.status_code == status.HTTP_200_OK
    sup_items = sup_resp.data["results"] if isinstance(sup_resp.data, dict) and "results" in sup_resp.data else sup_resp.data
    codes = [s["code"] for s in sup_items]
    assert "SUP-A" in codes
    assert "SUP-B" not in codes

    # 5. Purchases
    po_resp = client.get("/api/v1/purchases/")
    assert po_resp.status_code == status.HTTP_200_OK
    po_items = po_resp.data["results"] if isinstance(po_resp.data, dict) and "results" in po_resp.data else po_resp.data
    po_nums = [po["po_number"] for po in po_items]
    assert "PO-ALPHA-01" in po_nums
    assert "PO-BETA-01" not in po_nums
