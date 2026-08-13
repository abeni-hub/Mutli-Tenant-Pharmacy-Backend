from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.inventory.models import InventoryLog, StockBatch
from apps.subscriptions.models import SubscriptionPlan, TenantSubscription
from apps.tenants.models import Membership, Tenant
from apps.tenants.services import TenantCreateData, TenantService


@pytest.mark.django_db
class TestPurchasingSystem:
    def setup_method(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="purchasing-owner@abeni.test",
            password="Password123!",
        )
        self.pharmacist = User.objects.create_user(
            email="purchasing-pharmacist@abeni.test",
            password="Password123!",
            first_name="Pharma",
            last_name="Staff",
        )
        self.tenant = TenantService.create_for_owner(
            self.owner,
            TenantCreateData(name="Purchase Test Pharmacy"),
        )
        Membership.objects.create(tenant=self.tenant, user=self.pharmacist, role=Membership.Role.PHARMACIST)

        plan = SubscriptionPlan.objects.get(code="enterprise")
        TenantSubscription.objects.create(
            tenant=self.tenant,
            plan=plan,
            status=TenantSubscription.Status.ACTIVE,
            billing_cycle=TenantSubscription.BillingCycle.YEARLY,
            starts_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=365),
        )

        self.product = Product.objects.create(
            tenant=self.tenant,
            name="Amoxicillin 500mg",
            sku="AMOX-500",
            reorder_level=10,
        )

        self.owner_token = self._get_token(self.owner)
        self.pharmacist_token = self._get_token(self.pharmacist)

    def _get_token(self, user):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": "Password123!"},
            format="json",
        )
        assert response.status_code == 200, response.data
        return response.data["access"]

    def test_supplier_crud_and_purchase_flow(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")

        supplier_response = self.client.post(
            "/api/v1/suppliers/",
            {
                "code": "SUP-001",
                "company_name": "MedFlow Suppliers",
                "contact_person": "Nedim Bekele",
                "email": "nedim@medflow.test",
                "phone": "+251911111111",
                "address": "Addis Ababa",
                "country": "Ethiopia",
                "tax_number": "TAX-001",
                "license_number": "LIC-001",
                "payment_terms": "Net 30",
                "status": "active",
                "preferred_supplier": True,
                "notes": "Preferred distributor",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        assert supplier_response.status_code == 201, supplier_response.data
        supplier_id = supplier_response.data["id"]

        create_po = self.client.post(
            "/api/v1/purchases/",
            {
                "po_number": "PO-1001",
                "supplier": supplier_id,
                "branch": "Downtown",
                "warehouse": "Main Warehouse",
                "expected_delivery": (timezone.now().date() + timedelta(days=7)).isoformat(),
                "notes": "Initial order",
                "status": "draft",
                "discount": "10.00",
                "tax": "15.00",
                "items": [
                    {
                        "product": str(self.product.id),
                        "ordered_quantity": 20,
                        "unit_cost": "5.00",
                        "discount": "0.00",
                        "tax": "0.00",
                    }
                ],
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        assert create_po.status_code == 201, create_po.data
        purchase_id = create_po.data["id"]
        assert create_po.data["status"] == "draft"
        assert create_po.data["total"] == "100.00"

        approve_response = self.client.post(
            f"/api/v1/purchases/{purchase_id}/approve/",
            {},
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )
        assert approve_response.status_code == 200, approve_response.data
        assert approve_response.data["status"] == "approved"

        receive_response = self.client.post(
            f"/api/v1/purchases/{purchase_id}/receive/",
            {"complete": True},
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        assert receive_response.status_code == 200, receive_response.data
        assert receive_response.data["status"] == "received"

        batch = StockBatch.unscoped.filter(purchase_order_reference="PO-1001").first()
        assert batch is not None
        assert batch.quantity == 20
        assert batch.supplier == "MedFlow Suppliers"

        log = InventoryLog.unscoped.filter(reference_number="PO-1001").first()
        assert log is not None
        assert log.transaction_type == InventoryLog.TransactionType.STOCK_IN

    def test_purchase_reports_and_tenant_isolation(self):
        other_tenant = Tenant.objects.create(name="Other Pharmacy", slug="other")
        other_owner = User.objects.create_user(email="other-owner@abeni.test", password="Password123!")
        Membership.objects.create(tenant=other_tenant, user=other_owner, role=Membership.Role.OWNER)
        other_product = Product.objects.create(tenant=other_tenant, name="Other Item", sku="OTHER-1")

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")
        supplier = self.client.post(
            "/api/v1/suppliers/",
            {
                "code": "SUP-002",
                "company_name": "Alpha Distributors",
                "contact_person": "Sara",
                "email": "sara@alpha.test",
                "phone": "+251911111112",
                "address": "Addis Ababa",
                "country": "Ethiopia",
                "tax_number": "TAX-002",
                "license_number": "LIC-002",
                "payment_terms": "Net 15",
                "status": "active",
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )
        assert supplier.status_code == 201

        other_supplier = self.client.post(
            "/api/v1/suppliers/",
            {
                "code": "SUP-003",
                "company_name": "Beta Distributors",
                "contact_person": "John",
                "email": "john@beta.test",
                "phone": "+251911111113",
                "address": "Addis Ababa",
                "country": "Ethiopia",
                "tax_number": "TAX-003",
                "license_number": "LIC-003",
                "payment_terms": "Net 15",
                "status": "active",
            },
            HTTP_X_TENANT_ID=str(other_tenant.id),
            format="json",
        )
        assert other_supplier.status_code == 403

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.owner_token}")
        list_response = self.client.get(
            "/api/v1/suppliers/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert list_response.status_code == 200
        assert len(list_response.data["results"]) == 1
        assert list_response.data["results"][0]["company_name"] == "Alpha Distributors"

        self.client.post(
            "/api/v1/purchases/",
            {
                "po_number": "PO-2001",
                "supplier": supplier.data["id"],
                "branch": "North",
                "warehouse": "North Warehouse",
                "expected_delivery": (timezone.now().date() + timedelta(days=5)).isoformat(),
                "status": "draft",
                "items": [
                    {
                        "product": str(self.product.id),
                        "ordered_quantity": 10,
                        "unit_cost": "3.50",
                        "discount": "0.00",
                        "tax": "0.00",
                    }
                ],
            },
            HTTP_X_TENANT_ID=str(self.tenant.id),
            format="json",
        )

        report_response = self.client.get(
            "/api/v1/purchases/summary/",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        assert report_response.status_code == 200
        assert report_response.data["total_purchases"] == 1
