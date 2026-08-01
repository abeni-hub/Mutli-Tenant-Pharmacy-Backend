from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.inventory.services import InventoryService
from apps.reports.services import ReportService
from apps.sales.services import SaleService
from apps.subscriptions.models import SubscriptionPlan, TenantSubscription
from apps.tenants.models import Membership, Tenant
from apps.tenants.services import TenantCreateData, TenantService


@pytest.mark.django_db
class TestReportsSystem:
    def setup_method(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="reportowner@abeni.test", password="Password123!"
        )
        self.cashier = User.objects.create_user(
            email="reportcashier@abeni.test", password="Password123!", first_name="Betelehem", last_name="Cashier"
        )
        self.tenant = TenantService.create_for_owner(
            self.owner, TenantCreateData(name="Reports Test Pharmacy")
        )
        Membership.objects.create(
            tenant=self.tenant, user=self.cashier, role=Membership.Role.CASHIER
        )

        # Active Enterprise Subscription
        plan = SubscriptionPlan.objects.get(code="enterprise")
        TenantSubscription.objects.create(
            tenant=self.tenant,
            plan=plan,
            status=TenantSubscription.Status.ACTIVE,
            billing_cycle=TenantSubscription.BillingCycle.YEARLY,
            starts_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=365),
        )

        # Create Products
        self.p1 = Product.objects.create(
            tenant=self.tenant, name="Panadol Extra", sku="PAN-01", reorder_level=10
        )
        self.p2 = Product.objects.create(
            tenant=self.tenant, name="Ibuprofen 400mg", sku="IBU-01", reorder_level=10
        )

        today = timezone.now().date()

        # Add Stock Batches
        InventoryService.stock_in(
            tenant=self.tenant,
            product=self.p1,
            batch_number="B-PAN-100",
            quantity=100,
            expiry_date=today + timedelta(days=180),
            unit_price=2.00,
            selling_price=5.00,
            performed_by=self.owner,
        )
        InventoryService.stock_in(
            tenant=self.tenant,
            product=self.p2,
            batch_number="B-IBU-50",
            quantity=50,
            expiry_date=today + timedelta(days=200),
            unit_price=4.00,
            selling_price=10.00,
            performed_by=self.owner,
        )

        # Process a checkout sale
        SaleService.create_sale(
            tenant=self.tenant,
            cashier=self.cashier,
            items_data=[
                {"product_id": str(self.p1.id), "quantity": 10},  # 10 * 5.00 = 50.00, cost = 20.00, profit = 30.00
                {"product_id": str(self.p2.id), "quantity": 5},   # 5 * 10.00 = 50.00, cost = 20.00, profit = 30.00
            ],
            payment_method="cash",
        )

        self.owner_token = self._get_token(self.owner)
        self.cashier_token = self._get_token(self.cashier)

    def test_01_dashboard_stats(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")
        res = self.client.get(
            "/api/v1/reports/dashboard/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert res.status_code == 200, res.data
        data = res.data
        assert "today" in data
        assert "this_month" in data
        assert "inventory_summary" in data
        assert data["today"]["sales_count"] == 1
        assert float(data["today"]["revenue"]) == 100.00
        assert float(data["today"]["profit"]) == 60.00

    def test_02_financial_report(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")
        res = self.client.get(
            "/api/v1/reports/financial/?period=monthly",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert res.status_code == 200, res.data
        data = res.data
        assert data["period_type"] == "monthly"
        assert float(data["totals"]["total_revenue"]) == 100.00
        assert float(data["totals"]["total_profit"]) == 60.00
        assert len(data["breakdown"]) >= 1

    def test_03_cashier_performance(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")
        res = self.client.get(
            "/api/v1/reports/cashier-performance/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert res.status_code == 200, res.data
        data = res.data
        assert len(data) == 1
        assert data[0]["cashier_email"] == "reportcashier@abeni.test"
        assert data[0]["sales_count"] == 1
        assert float(data[0]["total_revenue"]) == 100.00

    def test_04_product_performance(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")
        res = self.client.get(
            "/api/v1/reports/product-performance/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert res.status_code == 200, res.data
        data = res.data
        assert "top_medicines" in data
        assert "slow_medicines" in data
        assert len(data["top_medicines"]) >= 1
        top1 = data["top_medicines"][0]
        assert top1["quantity_sold"] == 10  # Panadol Extra (10 sold)

    def test_05_inventory_valuation(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")
        res = self.client.get(
            "/api/v1/reports/inventory-valuation/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert res.status_code == 200, res.data
        data = res.data
        assert data["total_active_batches"] == 2
        assert data["total_items_in_stock"] == 135  # (100-10) + (50-5) = 90 + 45 = 135
        # Cost valuation = (90 * 2.00) + (45 * 4.00) = 180 + 180 = 360.00
        assert float(data["cost_valuation"]) == 360.00
        # Retail valuation = (90 * 5.00) + (45 * 10.00) = 450 + 450 = 900.00
        assert float(data["retail_valuation"]) == 900.00

    def test_06_charts_api(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")
        res = self.client.get(
            "/api/v1/reports/charts/?period=monthly",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert res.status_code == 200, res.data
        data = res.data
        assert data["period"] == "monthly"
        assert len(data["labels"]) == 12
        assert "revenue" in data["datasets"]
        assert "profit" in data["datasets"]

    def test_07_inventory_alerts(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")
        alert_product = Product.objects.create(
            tenant=self.tenant,
            name="Amoxicillin 250mg",
            sku="AMX-250",
            reorder_level=10,
        )
        InventoryService.stock_in(
            tenant=self.tenant,
            product=alert_product,
            batch_number="B-AMX-001",
            quantity=3,
            expiry_date=timezone.now().date() + timedelta(days=5),
            unit_price=1.50,
            selling_price=3.00,
            performed_by=self.owner,
        )

        res = self.client.get(
            "/api/v1/reports/alerts/?days=30",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert res.status_code == 200, res.data
        data = res.data
        assert "low_stock" in data
        assert "near_expiry" in data
        assert any(item["product_name"] == "Amoxicillin 250mg" for item in data["low_stock"])
        assert any(item["product_name"] == "Amoxicillin 250mg" for item in data["near_expiry"])

    def _get_token(self, user: User) -> str:
        login_res = self.client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": "Password123!"},
            format="json",
        )
        return login_res.data["access"]
