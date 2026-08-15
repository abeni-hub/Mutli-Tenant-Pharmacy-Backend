import pytest
from rest_framework import status
from rest_framework.test import APIClient
from django.core.management import call_command


@pytest.fixture
def owner_api_client(db):
    """Seed Owner demo data and return authenticated APIClient."""
    call_command("seed_owner_demo")
    from apps.accounts.models import User
    from apps.tenants.models import Membership

    owner = User.objects.get(email="owner@abeni.test")
    membership = Membership.objects.get(user=owner, is_active=True)
    tenant_id = str(membership.tenant_id)

    client = APIClient()
    login_resp = client.post("/api/v1/auth/login/", {"email": "owner@abeni.test", "password": "SecurePassword123!"}, format="json")
    token = login_resp.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=tenant_id)

    return {"client": client, "tenant_id": tenant_id, "user": owner}


@pytest.mark.django_db
def test_get_dashboard_owner_endpoint(owner_api_client):
    client = owner_api_client["client"]

    # 1. GET /api/v1/dashboard/owner/
    resp = client.get("/api/v1/dashboard/owner/")
    assert resp.status_code == status.HTTP_200_OK

    data = resp.data
    assert "kpis" in data
    assert "recent_activities" in data or "recent_activity" in data


@pytest.mark.django_db
def test_get_reports_dashboard_endpoint(owner_api_client):
    client = owner_api_client["client"]

    # 2. GET /api/v1/reports/dashboard/
    resp = client.get("/api/v1/reports/dashboard/")
    assert resp.status_code == status.HTTP_200_OK

    data = resp.data
    assert "today" in data
    assert "this_month" in data
    assert "inventory_summary" in data

    today = data["today"]
    inv = data["inventory_summary"]

    assert "revenue" in today
    assert "sales_count" in today
    assert "profit" in today

    assert "low_stock_products" in inv
    assert "near_expiry_batches" in inv
    assert "inventory_value" in inv
    assert "supplier_count" in inv
    assert "pending_purchases_count" in inv


@pytest.mark.django_db
def test_get_reports_charts_endpoint(owner_api_client):
    client = owner_api_client["client"]

    # 3. GET /api/v1/reports/charts/
    resp = client.get("/api/v1/reports/charts/?period=monthly")
    assert resp.status_code == status.HTTP_200_OK

    data = resp.data
    assert "datasets" in data or "chart_type" in data or "period" in data
