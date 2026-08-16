import pytest
from rest_framework.test import APIClient
from apps.accounts.models import User
from apps.catalog.models import Product
from apps.tenants.models import Tenant, Membership

@pytest.mark.django_db
class TestProductsAPI:
    @pytest.fixture(autouse=True)
    def setup_data(self):
        self.client = APIClient()

        # Tenant Alpha & Owner Alpha
        self.tenant_a = Tenant.objects.create(name="Tenant Alpha", slug="tenant-alpha-prod", registration_number="REG-P-01")
        self.owner_a = User.objects.create_user(
            email="owner_a_prod@alpha.test",
            password="Password123!",
            first_name="Owner",
            last_name="Alpha",
        )
        Membership.objects.create(user=self.owner_a, tenant=self.tenant_a, role=Membership.Role.OWNER, is_active=True)

        # Tenant Beta & Owner Beta
        self.tenant_b = Tenant.objects.create(name="Tenant Beta", slug="tenant-beta-prod", registration_number="REG-P-02")
        self.owner_b = User.objects.create_user(
            email="owner_b_prod@beta.test",
            password="Password123!",
            first_name="Owner",
            last_name="Beta",
        )
        Membership.objects.create(user=self.owner_b, tenant=self.tenant_b, role=Membership.Role.OWNER, is_active=True)

    def test_1_tenant_a_creates_product(self):
        """Tenant A creates a new medicine product -> 201 Created and saved in DB"""
        self.client.force_authenticate(user=self.owner_a)
        res = self.client.post(
            "/api/v1/products/",
            {
                "name": "Amoxicillin 500mg",
                "generic_name": "Amoxicillin",
                "brand_name": "Amoxil",
                "sku": "AMOX-500-001",
                "barcode": "8901234567890",
                "category": "Antibiotics",
                "manufacturer": "GSK",
                "purchase_price": "10.00",
                "selling_price": "15.50",
                "available_stock": 100,
                "min_stock": 20,
                "max_stock": 500,
                "unit": "pack",
                "dosage_form": "capsule",
                "status": "active",
            },
            HTTP_X_TENANT_ID=str(self.tenant_a.id),
            format="json",
        )
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "Amoxicillin 500mg"

        # Verify DB persistence
        prod = Product.unscoped.filter(id=data["id"]).first()
        assert prod is not None, f"Product {data['id']} not found in DB!"
        assert prod.tenant_id == self.tenant_a.id
        assert prod.sku == "AMOX-500-001"
        assert prod.available_stock == 100

    def test_2_tenant_b_isolation(self):
        """Tenant B cannot access Tenant A's products"""
        prod_a = Product.unscoped.create(
            tenant=self.tenant_a,
            name="Secret Product A",
            sku="SECRET-A",
            category="Antibiotics",
            purchase_price="5.00",
            selling_price="10.00",
        )

        self.client.force_authenticate(user=self.owner_b)
        res_get = self.client.get(
            f"/api/v1/products/{prod_a.id}/",
            HTTP_X_TENANT_ID=str(self.tenant_b.id),
        )
        assert res_get.status_code == 404

    def test_3_update_product(self):
        """Tenant A updates product details -> 200 OK"""
        prod = Product.unscoped.create(
            tenant=self.tenant_a,
            name="Paracetamol 500mg",
            sku="PARA-500",
            category="Analgesics",
            purchase_price="2.00",
            selling_price="4.00",
            available_stock=50,
        )

        self.client.force_authenticate(user=self.owner_a)
        res_patch = self.client.patch(
            f"/api/v1/products/{prod.id}/",
            {"selling_price": "5.50", "available_stock": 120},
            HTTP_X_TENANT_ID=str(self.tenant_a.id),
            format="json",
        )
        assert res_patch.status_code == 200
        prod.refresh_from_db()
        assert float(prod.selling_price) == 5.50
        assert prod.available_stock == 120

    def test_4_delete_product(self):
        """Tenant A deletes a product -> 204 No Content and removed from DB"""
        prod = Product.unscoped.create(
            tenant=self.tenant_a,
            name="Obsolete Product",
            sku="OBS-001",
            category="General",
        )

        self.client.force_authenticate(user=self.owner_a)
        res_del = self.client.delete(
            f"/api/v1/products/{prod.id}/",
            HTTP_X_TENANT_ID=str(self.tenant_a.id),
        )
        assert res_del.status_code == 204
        assert not Product.unscoped.filter(id=prod.id).exists()

    def test_5_categories_and_summary_endpoints(self):
        """Test categories and summary API endpoints for Tenant A"""
        Product.unscoped.create(
            tenant=self.tenant_a,
            name="Metformin 850mg",
            sku="MET-850",
            category="Diabetes",
            status="active",
            available_stock=5,
            min_stock=10,
        )

        self.client.force_authenticate(user=self.owner_a)
        res_cat = self.client.get("/api/v1/products/categories/", HTTP_X_TENANT_ID=str(self.tenant_a.id))
        assert res_cat.status_code == 200
        categories = res_cat.json()
        assert "Diabetes" in categories

        res_sum = self.client.get("/api/v1/products/summary/", HTTP_X_TENANT_ID=str(self.tenant_a.id))
        assert res_sum.status_code == 200
        sum_data = res_sum.json()
        assert sum_data["total"] >= 1
        assert sum_data["low_stock"] >= 1
