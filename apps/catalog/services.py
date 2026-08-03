from uuid import UUID

from apps.catalog.models import Product
from apps.catalog.serializers import ProductSerializer
from core.repositories import TenantScopedRepository


class ProductRepository(TenantScopedRepository[Product]):
    model = Product

    def get_by_sku(self, sku: str) -> Product | None:
        return self.queryset().filter(sku__iexact=sku).first()

    def get_by_barcode(self, barcode: str) -> Product | None:
        return self.queryset().filter(barcode=barcode).first()


class ProductService:
    @staticmethod
    def create(*, tenant_id: UUID, data: dict) -> Product:
        serializer = ProductSerializer(data=data, context={"tenant_id": tenant_id})
        serializer.is_valid(raise_exception=True)
        return serializer.save(tenant_id=tenant_id)

    @staticmethod
    def update(*, tenant_id: UUID, product: Product, data: dict) -> Product:
        serializer = ProductSerializer(product, data=data, partial=True, context={"tenant_id": tenant_id})
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    @staticmethod
    def queryset(*, tenant_id: UUID):
        return Product.objects.filter(tenant_id=tenant_id)

    @staticmethod
    def repository(*, tenant_id: UUID) -> ProductRepository:
        return ProductRepository(tenant_id)
