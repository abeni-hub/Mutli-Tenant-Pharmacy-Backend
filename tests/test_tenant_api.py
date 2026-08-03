from datetime import date

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.tenants.models import Membership, Tenant


class TenantApiTests(APITestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="correct horse battery staple",
            first_name="Ada",
            last_name="Owner",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="correct horse battery staple",
            first_name="Grace",
            last_name="Other",
        )

    def authenticate(self, email: str, password: str) -> None:
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": email, "password": password},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")

    def test_owner_can_create_and_list_tenant(self) -> None:
        self.authenticate("owner@example.com", "correct horse battery staple")
        create_response = self.client.post(
            "/api/v1/tenants/",
            {"name": "Central Pharmacy", "registration_number": "RX-001"},
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        tenant_id = create_response.data["id"]

        list_response = self.client.get("/api/v1/tenants/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in list_response.data], [tenant_id])

    def test_user_cannot_access_another_users_tenant(self) -> None:
        tenant = Tenant.objects.create(name="Private Pharmacy", slug="private-pharmacy")
        Membership.objects.create(
            tenant=tenant,
            user=self.user,
            role=Membership.Role.OWNER,
        )
        self.authenticate("other@example.com", "correct horse battery staple")

        response = self.client.get(
            f"/api/v1/tenant-context/{tenant.id}/",
            HTTP_X_TENANT_ID=str(tenant.id),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_tenant_context_requires_header(self) -> None:
        tenant = Tenant.objects.create(name="Header Pharmacy", slug="header-pharmacy")
        Membership.objects.create(
            tenant=tenant,
            user=self.user,
            role=Membership.Role.OWNER,
        )
        self.authenticate("owner@example.com", "correct horse battery staple")

        response = self.client.get(f"/api/v1/tenant-context/{tenant.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_product_isolation_returns_not_found_for_foreign_uuid(self) -> None:
        first_tenant = Tenant.objects.create(name="First Pharmacy", slug="first")
        second_tenant = Tenant.objects.create(name="Second Pharmacy", slug="second")
        Membership.objects.create(
            tenant=first_tenant, user=self.user, role=Membership.Role.OWNER
        )
        product = Product.objects.create(
            tenant=second_tenant, name="Private Medicine", sku="PRIVATE-1"
        )
        self.authenticate("owner@example.com", "correct horse battery staple")

        response = self.client.get(
            f"/api/v1/products/{product.id}/",
            HTTP_X_TENANT_ID=str(first_tenant.id),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_can_read_products_only_in_active_tenant(self) -> None:
        tenant = Tenant.objects.create(name="Staff Pharmacy", slug="staff")
        Membership.objects.create(
            tenant=tenant, user=self.user, role=Membership.Role.CASHIER
        )
        product = Product.objects.create(
            tenant=tenant, name="Staff Medicine", sku="STAFF-1"
        )
        self.authenticate("owner@example.com", "correct horse battery staple")

        response = self.client.get(
            f"/api/v1/products/{product.id}/",
            HTTP_X_TENANT_ID=str(tenant.id),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_malformed_tenant_header_is_rejected_before_view(self) -> None:
        self.authenticate("owner@example.com", "correct horse battery staple")

        response = self.client.get(
            "/api/v1/products/00000000-0000-0000-0000-000000000000/",
            HTTP_X_TENANT_ID="not-a-uuid",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_super_admin_can_access_active_tenant(self) -> None:
        User.objects.create_superuser(
            email="admin@example.com",
            password="correct horse battery staple",
            first_name="Super",
            last_name="Admin",
        )
        tenant = Tenant.objects.create(name="Admin Pharmacy", slug="admin")
        product = Product.objects.create(
            tenant=tenant, name="Admin Medicine", sku="ADMIN-1"
        )
        self.authenticate("admin@example.com", "correct horse battery staple")

        response = self.client.get(
            f"/api/v1/products/{product.id}/",
            HTTP_X_TENANT_ID=str(tenant.id),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(product.id))

    def test_product_api_persists_enterprise_fields_in_postgres(self) -> None:
        tenant = Tenant.objects.create(name="Enterprise Pharmacy", slug="enterprise")
        Membership.objects.create(tenant=tenant, user=self.user, role=Membership.Role.OWNER)
        self.authenticate("owner@example.com", "correct horse battery staple")

        response = self.client.post(
            "/api/v1/products/",
            {
                "name": "Amoxicillin 500mg",
                "sku": "AMX-500-001",
                "generic_name": "Amoxicillin",
                "brand_name": "Amoxil",
                "barcode": "5012345678901",
                "category": "Antibiotics",
                "manufacturer": "PharmaCo",
                "purchase_price": "12.50",
                "selling_price": "18.75",
                "tax_rate": "8.5",
                "available_stock": 25,
                "min_stock": 10,
                "max_stock": 100,
                "unit": "pack",
                "strength": "500mg",
                "dosage_form": "tablet",
                "batch_number": "BATCH-001",
                "expiry_date": "2027-12-31",
                "description": "Enterprise pharmacy stock item",
                "requires_prescription": True,
                "controlled_drug": False,
                "refrigerated": True,
                "image_url": "https://example.com/amoxicillin.png",
                "reorder_level": 15,
                "status": "active",
            },
            format="json",
            HTTP_X_TENANT_ID=str(tenant.id),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        product = Product.unscoped.get(id=response.data["id"])
        self.assertEqual(product.brand_name, "Amoxil")
        self.assertEqual(product.barcode, "5012345678901")
        self.assertEqual(product.category, "Antibiotics")
        self.assertEqual(product.manufacturer, "PharmaCo")
        self.assertEqual(product.purchase_price, 12.50)
        self.assertEqual(product.selling_price, 18.75)
        self.assertEqual(product.tax_rate, 8.5)
        self.assertEqual(product.available_stock, 25)
        self.assertEqual(product.min_stock, 10)
        self.assertEqual(product.max_stock, 100)
        self.assertEqual(product.unit, "pack")
        self.assertEqual(product.strength, "500mg")
        self.assertEqual(product.dosage_form, "tablet")
        self.assertEqual(product.batch_number, "BATCH-001")
        self.assertEqual(product.expiry_date, date(2027, 12, 31))
        self.assertEqual(response.data["expiry_date"], "2027-12-31")
        self.assertEqual(product.reorder_level, 15)
        self.assertEqual(product.description, "Enterprise pharmacy stock item")
        self.assertTrue(product.requires_prescription)
        self.assertFalse(product.controlled_drug)
        self.assertTrue(product.refrigerated)
        self.assertEqual(product.image_url, "https://example.com/amoxicillin.png")
        self.assertTrue(product.is_active)
        self.assertEqual(product.status, "active")
