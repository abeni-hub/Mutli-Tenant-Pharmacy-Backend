from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.inventory.models import InventoryLog, StockBatch
from apps.inventory.services import InventoryService
from apps.subscriptions.models import SubscriptionPlan, TenantSubscription
from apps.tenants.models import Tenant
from apps.tenants.services import TenantCreateData, TenantService


@pytest.mark.django_db
class TestInventorySystem:
    def setup_method(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="invowner@abeni.test", password="Password123!"
        )
        self.tenant = TenantService.create_for_owner(
            self.owner, TenantCreateData(name="Inventory Test Pharmacy")
        )

        # Grant active Enterprise subscription so feature restrictions don't block
        plan = SubscriptionPlan.objects.get(code="enterprise")
        TenantSubscription.objects.create(
            tenant=self.tenant,
            plan=plan,
            status=TenantSubscription.Status.ACTIVE,
            billing_cycle=TenantSubscription.BillingCycle.YEARLY,
            starts_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=365),
        )

        # Create test products
        self.paracetamol = Product.objects.create(
            tenant=self.tenant,
            name="Paracetamol 500mg",
            sku="PARA-500",
            reorder_level=10,
        )
        self.amoxicillin = Product.objects.create(
            tenant=self.tenant,
            name="Amoxicillin 250mg",
            sku="AMOX-250",
            reorder_level=20,
        )

        self.token = self._get_token(self.owner)

    def test_01_stock_in_creates_batch_and_inventory_log(self):
        expiry = timezone.now().date() + timedelta(days=180)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

        res = self.client.post(
            "/api/v1/inventory/batches/stock-in/",
            {
                "product_id": str(self.paracetamol.id),
                "batch_number": "BATCH-001",
                "quantity": 100,
                "expiry_date": expiry.isoformat(),
                "unit_price": "5.00",
                "selling_price": "8.50",
                "supplier": "MedPharma PLC",
                "reference_number": "PO-1001",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        assert res.status_code == 201, res.data
        assert res.data["batch_number"] == "BATCH-001"
        assert res.data["quantity"] == 100
        assert res.data["unit_price"] == "5.00"
        assert res.data["selling_price"] == "8.50"

        # Verify InventoryLog
        log = InventoryLog.unscoped.get(batch_id=res.data["id"])
        assert log.transaction_type == InventoryLog.TransactionType.STOCK_IN
        assert log.quantity_changed == 100
        assert log.reference_number == "PO-1001"

    def test_02_stock_out_fifo_algorithm(self):
        today = timezone.now().date()
        # Batch 1: Earliest Expiry (30 days), Qty = 20
        batch1 = InventoryService.stock_in(
            tenant=self.tenant,
            product=self.paracetamol,
            batch_number="BATCH-EARLY-30",
            quantity=20,
            expiry_date=today + timedelta(days=30),
            unit_price=5.00,
            selling_price=8.50,
            performed_by=self.owner,
        )

        # Batch 2: Later Expiry (90 days), Qty = 50
        batch2 = InventoryService.stock_in(
            tenant=self.tenant,
            product=self.paracetamol,
            batch_number="BATCH-LATE-90",
            quantity=50,
            expiry_date=today + timedelta(days=90),
            unit_price=5.00,
            selling_price=8.50,
            performed_by=self.owner,
        )

        # Perform FIFO Stock Out of 30 units (Should take 20 from batch1, 10 from batch2)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        res = self.client.post(
            "/api/v1/inventory/batches/stock-out-fifo/",
            {
                "product_id": str(self.paracetamol.id),
                "quantity": 30,
                "reason": "Prescription Dispense #102",
                "reference_number": "INV-2001",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        assert res.status_code == 200, res.data
        deductions = res.data["deductions"]
        assert len(deductions) == 2

        # Check First Deduction (Batch 1: 20 units)
        assert str(deductions[0]["batch_id"]) == str(batch1.id)
        assert deductions[0]["quantity_deducted"] == 20
        assert deductions[0]["remaining_batch_qty"] == 0

        # Check Second Deduction (Batch 2: 10 units)
        assert str(deductions[1]["batch_id"]) == str(batch2.id)
        assert deductions[1]["quantity_deducted"] == 10
        assert deductions[1]["remaining_batch_qty"] == 40

        # Refresh from DB
        batch1.refresh_from_db()
        batch2.refresh_from_db()
        assert batch1.quantity == 0
        assert batch2.quantity == 40

    def test_03_stock_adjustment_updates_quantity_and_logs_reason(self):
        today = timezone.now().date()
        batch = InventoryService.stock_in(
            tenant=self.tenant,
            product=self.amoxicillin,
            batch_number="BATCH-AMOX-01",
            quantity=50,
            expiry_date=today + timedelta(days=120),
            unit_price=10.00,
            selling_price=15.00,
            performed_by=self.owner,
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        res = self.client.post(
            "/api/v1/inventory/batches/adjust/",
            {
                "batch_id": str(batch.id),
                "new_quantity": 45,
                "reason": "Damaged bottle discarded during audit",
                "reference_number": "AUDIT-2026-07",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        assert res.status_code == 200, res.data
        assert res.data["quantity"] == 45

        # Check InventoryLog for adjustment
        log = InventoryLog.unscoped.filter(
            batch=batch, transaction_type=InventoryLog.TransactionType.ADJUSTMENT
        ).first()
        assert log is not None
        assert log.quantity_changed == -5
        assert log.previous_quantity == 50
        assert log.new_quantity == 45
        assert log.reason == "Damaged bottle discarded during audit"

    def test_04_expired_and_near_expiry_queries(self):
        today = timezone.now().date()

        # Batch 1: Expired (10 days ago)
        InventoryService.stock_in(
            tenant=self.tenant,
            product=self.paracetamol,
            batch_number="BATCH-EXPIRED",
            quantity=15,
            expiry_date=today - timedelta(days=10),
            unit_price=4.00,
            selling_price=6.00,
        )

        # Batch 2: Near Expiry (expires in 20 days)
        InventoryService.stock_in(
            tenant=self.tenant,
            product=self.paracetamol,
            batch_number="BATCH-NEAR",
            quantity=30,
            expiry_date=today + timedelta(days=20),
            unit_price=4.00,
            selling_price=6.00,
        )

        # Batch 3: Fresh Stock (expires in 300 days)
        InventoryService.stock_in(
            tenant=self.tenant,
            product=self.paracetamol,
            batch_number="BATCH-FRESH",
            quantity=100,
            expiry_date=today + timedelta(days=300),
            unit_price=4.00,
            selling_price=6.00,
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

        # GET Expired
        res_expired = self.client.get(
            "/api/v1/inventory/batches/expired/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert res_expired.status_code == 200
        assert len(res_expired.data) == 1
        assert res_expired.data[0]["batch_number"] == "BATCH-EXPIRED"

        # GET Near Expiry (60 days)
        res_near = self.client.get(
            "/api/v1/inventory/batches/near-expiry/?days=60",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert res_near.status_code == 200
        assert len(res_near.data) == 1
        assert res_near.data[0]["batch_number"] == "BATCH-NEAR"

    def test_05_low_stock_query(self):
        today = timezone.now().date()
        # Amoxicillin has reorder_level = 20.
        # Receive only 5 items -> should be flagged as Low Stock
        InventoryService.stock_in(
            tenant=self.tenant,
            product=self.amoxicillin,
            batch_number="BATCH-AMOX-LOW",
            quantity=5,
            expiry_date=today + timedelta(days=100),
            unit_price=10.00,
            selling_price=15.00,
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        res = self.client.get(
            "/api/v1/inventory/batches/low-stock/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert res.status_code == 200
        low_stock_skus = [item["sku"] for item in res.data]
        assert "AMOX-250" in low_stock_skus

    def test_06_insufficient_stock_raises_validation_error(self):
        today = timezone.now().date()
        InventoryService.stock_in(
            tenant=self.tenant,
            product=self.paracetamol,
            batch_number="BATCH-SMALL",
            quantity=5,
            expiry_date=today + timedelta(days=60),
            unit_price=5.00,
            selling_price=8.00,
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        # Try to deduct 50 units when only 5 exist
        res = self.client.post(
            "/api/v1/inventory/batches/stock-out-fifo/",
            {
                "product_id": str(self.paracetamol.id),
                "quantity": 50,
                "reason": "Excessive deduction",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )
        assert res.status_code == 400
        assert "quantity" in res.data["error"]

    def test_07_inventory_logs_audit_trail(self):
        today = timezone.now().date()
        batch = InventoryService.stock_in(
            tenant=self.tenant,
            product=self.paracetamol,
            batch_number="BATCH-LOG-TEST",
            quantity=50,
            expiry_date=today + timedelta(days=100),
            unit_price=5.00,
            selling_price=8.00,
        )
        InventoryService.stock_out_fifo(
            tenant=self.tenant,
            product=self.paracetamol,
            quantity=10,
            reason="Test Dispense",
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        res = self.client.get(
            "/api/v1/inventory/logs/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert res.status_code == 200
        assert len(res.data) >= 2

    def _get_token(self, user: User) -> str:
        login_res = self.client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": "Password123!"},
            format="json",
        )
        return login_res.data["access"]
