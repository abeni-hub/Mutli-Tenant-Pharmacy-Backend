from rest_framework import viewsets

from apps.catalog.models import Product
from apps.catalog.serializers import ProductSerializer
from core.api.permissions import TenantMembershipPermission


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = (TenantMembershipPermission,)
    search_fields = ("name", "sku", "generic_name")
    ordering_fields = ("name", "sku", "created_at")
    filterset_fields = ("is_active",)

    def get_queryset(self):
        return Product.objects.all()

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.tenant_id)
