from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.inventory.models import InventoryLog, StockBatch
from apps.inventory.services import InventoryService
from apps.sales.models import Sale, SaleItem, SaleRefund
from apps.subscriptions.models import SubscriptionPlan, TenantSubscription
from apps.tenants.models import Tenant
from apps.tenants.services import TenantCreateData, TenantService


@pytest.mark.django_db
class TestSalesSystem:
    def setup_method(self):
        self.client = APIClient()
        self.cashier = User.objects.create_user(
            email="cashier1@abeni.test", password="Password123!", first_name="Abebe", last_name="Cashier"
        )
        self.owner = User.objects.create_user(
            email="salesowner@abeni.test", password="Password123!"
        )
        self.tenant = TenantService.create_for_owner(
            self.owner, TenantCreateData(name="Sales Test Pharmacy")
        )
        from apps.tenants.models import Membership
        Membership.objects.create(
            tenant=self.tenant, user=self.cashier, role=Membership.Role.CASHIER
        )

        # Active Enterprise subscription
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
        self.paracetamol = Product.objects.create(
            tenant=self.tenant, name="Paracetamol 500mg", sku="PARA-500", reorder_level=10
        )
        self.amoxicillin = Product.objects.create(
            tenant=self.tenant, name="Amoxicillin 250mg", sku="AMOX-250", reorder_level=10
        )

        # Receive Stock Batches
        today = timezone.now().date()
        # Paracetamol Batch: 100 units @ Cost 4.00, Selling 10.00
        self.batch_para = InventoryService.stock_in(
            tenant=self.tenant,
            product=self.paracetamol,
            batch_number="BATCH-P-01",
            quantity=100,
            expiry_date=today + timedelta(days=180),
            unit_price=4.00,
            selling_price=10.00,
            supplier="PharmaSupplier",
            performed_by=self.owner,
        )

        # Amoxicillin Batch: 50 units @ Cost 8.00, Selling 20.00
        self.batch_amox = InventoryService.stock_in(
            tenant=self.tenant,
            product=self.amoxicillin,
            batch_number="BATCH-A-01",
            quantity=50,
            expiry_date=today + timedelta(days=200),
            unit_price=8.00,
            selling_price=20.00,
            supplier="PharmaSupplier",
            performed_by=self.owner,
        )

        self.token = self._get_token(self.cashier)

    def test_01_create_sale_without_tax_and_without_discount(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

        # Buy 5 Paracetamol (5 * 10 = 50.00) + 2 Amoxicillin (2 * 20 = 40.00) = 90.00 Total
        # Total Cost = (5 * 4.00) + (2 * 8.00) = 20 + 16 = 36.00
        # Expected Net Profit = 90.00 - 36.00 = 54.00
        res = self.client.post(
            "/api/v1/sales/",
            {
                "items": [
                    {"product_id": str(self.paracetamol.id), "quantity": 5},
                    {"product_id": str(self.amoxicillin.id), "quantity": 2},
                ],
                "customer_name": "Tadesse Worku",
                "payment_method": "cash",
                "tax_rate": "0.00",
                "discount_amount": "0.00",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        assert res.status_code == 201, res.data
        data = res.data
        assert data["invoice_number"].startswith("INV-")
        assert data["subtotal"] == "90.00"
        assert data["discount_amount"] == "0.00"
        assert data["tax_amount"] == "0.00"
        assert data["total_amount"] == "90.00"
        assert data["total_cost"] == "36.00"
        assert data["total_profit"] == "54.00"
        assert data["status"] == "completed"

        # Verify stock deducted in DB
        self.batch_para.refresh_from_db()
        self.batch_amox.refresh_from_db()
        assert self.batch_para.quantity == 95
        assert self.batch_amox.quantity == 48

    def test_02_create_sale_with_tax_and_discounts(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

        # Buy 10 Paracetamol @ 10.00 = 100.00 gross
        # Item discount = 10.00 -> Item Net = 90.00
        # Global discount = 10.00 -> Net Taxable = 80.00
        # Tax 15% VAT = 80.00 * 0.15 = 12.00
        # Total Amount = 80.00 + 12.00 = 92.00
        # Total Cost = 10 * 4.00 = 40.00
        # Total Profit = (92.00 - 12.00) - 40.00 = 40.00
        res = self.client.post(
            "/api/v1/sales/",
            {
                "items": [
                    {
                        "product_id": str(self.paracetamol.id),
                        "quantity": 10,
                        "discount_amount": "10.00",
                    }
                ],
                "customer_name": "Haile Selassie",
                "payment_method": "mobile_money",
                "discount_amount": "10.00",
                "tax_rate": "15.00",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        assert res.status_code == 201, res.data
        data = res.data
        assert data["is_taxable"] is True
        assert data["subtotal"] == "100.00"
        assert data["discount_amount"] == "20.00"  # 10 item + 10 global
        assert data["tax_amount"] == "12.00"
        assert data["total_amount"] == "92.00"
        assert data["total_cost"] == "40.00"
        assert data["total_profit"] == "40.00"

    def test_03_receipt_endpoint(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        sale_res = self.client.post(
            "/api/v1/sales/",
            {
                "items": [{"product_id": str(self.paracetamol.id), "quantity": 2}],
                "payment_method": "cash",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )
        sale_id = sale_res.data["id"]

        receipt_res = self.client.get(
            f"/api/v1/sales/{sale_id}/receipt/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert receipt_res.status_code == 200
        receipt = receipt_res.data
        assert "invoice_number" in receipt
        assert receipt["pharmacy_name"] == "Sales Test Pharmacy"
        assert len(receipt["items"]) == 1
        assert receipt["grand_total"] == "20.00"

    def test_04_cancel_sale_reverts_stock_to_inventory(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        sale_res = self.client.post(
            "/api/v1/sales/",
            {
                "items": [{"product_id": str(self.paracetamol.id), "quantity": 20}],
                "payment_method": "card",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )
        sale_id = sale_res.data["id"]

        self.batch_para.refresh_from_db()
        assert self.batch_para.quantity == 80  # 100 - 20

        # Cancel sale as owner/manager
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._get_token(self.owner)}")
        cancel_res = self.client.post(
            f"/api/v1/sales/{sale_id}/cancel/",
            {"reason": "Customer changed mind and walked away."},
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        assert cancel_res.status_code == 200, cancel_res.data
        assert cancel_res.data["sale"]["status"] == "cancelled"

        # Verify stock restored in DB
        self.batch_para.refresh_from_db()
        assert self.batch_para.quantity == 100

        # Verify return log created
        log = InventoryLog.unscoped.filter(
            reference_number=f"CANCEL-{sale_res.data['invoice_number']}"
        ).first()
        assert log is not None
        assert log.quantity_changed == 20

    def test_05_refund_sale_item(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        sale_res = self.client.post(
            "/api/v1/sales/",
            {
                "items": [{"product_id": str(self.amoxicillin.id), "quantity": 10}],
                "payment_method": "cash",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )
        sale_id = sale_res.data["id"]
        item_id = sale_res.data["items"][0]["id"]

        self.batch_amox.refresh_from_db()
        assert self.batch_amox.quantity == 40  # 50 - 10

        # Refund 3 units as owner/manager
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._get_token(self.owner)}")
        refund_res = self.client.post(
            f"/api/v1/sales/{sale_id}/refund/",
            {
                "item_id": item_id,
                "quantity": 3,
                "reason": "Expired seal broken on 3 items.",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        assert refund_res.status_code == 200, refund_res.data
        assert refund_res.data["refund"]["refund_amount"] == "60.00"  # 3 * 20.00

        # Stock restored by 3
        self.batch_amox.refresh_from_db()
        assert self.batch_amox.quantity == 43

    def test_06_sales_history_search_and_filtering(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.client.post(
            "/api/v1/sales/",
            {
                "items": [{"product_id": str(self.paracetamol.id), "quantity": 1}],
                "customer_name": "Target Customer",
                "payment_method": "card",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        res_list = self.client.get(
            "/api/v1/sales/?search=Target",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert res_list.status_code == 200
        assert len(res_list.data["results"] if isinstance(res_list.data, dict) else res_list.data) >= 1

    def test_07_sales_analytics_reporting(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        # Create 2 sales
        self.client.post(
            "/api/v1/sales/",
            {
                "items": [{"product_id": str(self.paracetamol.id), "quantity": 10}],  # 100.00, cost 40.00, profit 60.00
                "payment_method": "cash",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._get_token(self.owner)}")
        report_res = self.client.get(
            "/api/v1/sales/report/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )

        assert report_res.status_code == 200, report_res.data
        summary = report_res.data["summary"]
        assert summary["total_sales_count"] >= 1
        assert float(summary["total_revenue"]) > 0
        assert float(summary["total_profit"]) > 0

    def test_08_hold_and_resume_sale_without_deducting_stock(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        held_res = self.client.post(
            "/api/v1/sales/",
            {
                "items": [{"product_id": str(self.paracetamol.id), "quantity": 3}],
                "payment_method": "cash",
                "sale_status": "held",
                "branch": "Downtown Branch",
                "customer_name": "Walk-in Customer",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        assert held_res.status_code == 201, held_res.data
        assert held_res.data["status"] == "held"
        assert held_res.data["payment_status"] == "pending"
        self.batch_para.refresh_from_db()
        assert self.batch_para.quantity == 100

        resume_res = self.client.post(
            f"/api/v1/sales/{held_res.data['id']}/resume/",
            {},
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        assert resume_res.status_code == 200, resume_res.data
        assert resume_res.data["sale"]["status"] == "draft"

    def test_09_sales_reporting_endpoints(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.client.post(
            "/api/v1/sales/",
            {
                "items": [{"product_id": str(self.paracetamol.id), "quantity": 2}],
                "payment_method": "card",
                "branch": "North Branch",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._get_token(self.owner)}")
        daily_res = self.client.get(
            "/api/v1/sales/daily/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        payment_res = self.client.get(
            "/api/v1/sales/payment-summary/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )

        assert daily_res.status_code == 200, daily_res.data
        assert payment_res.status_code == 200, payment_res.data
        assert isinstance(daily_res.data, list)
        assert "card" in payment_res.data

    def _get_token(self, user: User) -> str:
        login_res = self.client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": "Password123!"},
            format="json",
        )
        return login_res.data["access"]
