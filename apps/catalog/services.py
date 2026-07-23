from uuid import UUID

from apps.catalog.models import Product


class ProductService:
    @staticmethod
    def create(*, tenant_id: UUID, data: dict) -> Product:
        return Product.objects.create(tenant_id=tenant_id, **data)

    @staticmethod
    def queryset(*, tenant_id: UUID):
        return Product.objects.filter(tenant_id=tenant_id)
