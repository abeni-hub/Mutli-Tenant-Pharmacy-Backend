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
        self.pharmacist = User.objects.create_user(
            email="reportpharmacist@abeni.test", password="Password123!", first_name="Marta", last_name="Pharmacist"
        )
        self.superuser = User.objects.create_superuser(
            email="reportsuper@abeni.test", password="Password123!"
        )
        self.tenant = TenantService.create_for_owner(
            self.owner, TenantCreateData(name="Reports Test Pharmacy")
        )
        Membership.objects.create(
            tenant=self.tenant, user=self.cashier, role=Membership.Role.CASHIER
        )
        Membership.objects.create(
            tenant=self.tenant, user=self.pharmacist, role=Membership.Role.PHARMACIST
        )

        # Active Enterprise Subscription
        plan = SubscriptionPlan.objects.get(code="enterprise")
        TenantSubscription.objects.update_or_create(
            tenant=self.tenant,
            defaults={
                "plan": plan,
                "status": TenantSubscription.Status.ACTIVE,
                "billing_cycle": TenantSubscription.BillingCycle.YEARLY,
                "starts_at": timezone.now(),
                "expires_at": timezone.now() + timedelta(days=365),
            },
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
        self.pharmacist_token = self._get_token(self.pharmacist)
        self.superuser_token = self._get_token(self.superuser)

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

    def test_08_overview_endpoint_includes_enterprise_kpis(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")
        res = self.client.get(
            "/api/v1/reports/overview/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert res.status_code == 200, res.data
        data = res.data
        assert "kpis" in data
        assert "widgets" in data
        assert "recent_activity" in data
        assert any(item["id"] == "revenue" for item in data["kpis"])
        assert any(item["id"] == "inventory" for item in data["widgets"])

    def test_09_analytics_endpoint_supports_trends_and_filters(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")
        res = self.client.get(
            "/api/v1/reports/analytics/?period=monthly&chart_type=revenue",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert res.status_code == 200, res.data
        data = res.data
        assert "summary" in data
        assert "trend" in data
        assert "top_products" in data
        assert "slow_moving_products" in data
        assert data["summary"]["sales_count"] >= 1
        assert len(data["trend"]["labels"]) == 12

    def test_10_role_dashboards_return_role_specific_payloads(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")
        owner_res = self.client.get(
            "/api/v1/dashboard/owner/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert owner_res.status_code == 200, owner_res.data
        assert "kpis" in owner_res.data
        assert "recent_activities" in owner_res.data

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.pharmacist_token}")
        pharmacist_res = self.client.get(
            "/api/v1/dashboard/pharmacist/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert pharmacist_res.status_code == 200, pharmacist_res.data
        assert "inventory_summary" in pharmacist_res.data
        assert "alerts" in pharmacist_res.data

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.cashier_token}")
        cashier_res = self.client.get(
            "/api/v1/dashboard/cashier/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert cashier_res.status_code == 200, cashier_res.data
        assert "today_sales" in cashier_res.data
        assert "recent_transactions" in cashier_res.data

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.superuser_token}")
        super_admin_res = self.client.get("/api/v1/dashboard/super-admin/")
        assert super_admin_res.status_code == 200, super_admin_res.data
        assert "platform_summary" in super_admin_res.data

    def test_11_cashier_cannot_access_purchases(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.cashier_token}")
        purchases_res = self.client.get(
            "/api/v1/purchases/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert purchases_res.status_code == 403

    def test_12_cashier_cannot_access_inventory_crud(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.cashier_token}")
        inventory_res = self.client.get(
            "/api/v1/inventory/batches/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert inventory_res.status_code == 403

    def _get_token(self, user: User) -> str:
        login_res = self.client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": "Password123!"},
            format="json",
        )
        return login_res.data["access"]
