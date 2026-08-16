from datetime import timedelta

from django.db import models
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.catalog.models import Product
from apps.catalog.serializers import ProductSerializer
from apps.catalog.services import ProductService
from core.api.permissions import TenantMembershipPermission


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = (IsAuthenticated, TenantMembershipPermission)
    search_fields = ("name", "sku", "generic_name", "brand_name", "category", "manufacturer")
    ordering_fields = ("name", "sku", "created_at", "selling_price", "available_stock")
    filterset_fields = (
        "is_active",
        "status",
        "category",
        "manufacturer",
        "brand_name",
        "requires_prescription",
        "controlled_drug",
        "refrigerated",
        "supplier_id",
    )

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            return Product.objects.none()
        return ProductService.queryset(tenant_id=tenant_id)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["tenant_id"] = getattr(self.request, "tenant_id", None)
        return context

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        serializer.save(tenant_id=tenant_id)

    def perform_update(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        serializer.save(tenant_id=tenant_id)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        queryset = self.get_queryset()
        return Response(
            {
                "total": queryset.count(),
                "active": queryset.filter(status="active").count(),
                "low_stock": queryset.filter(available_stock__lt=models.F("min_stock")).count(),
                "near_expiry": queryset.filter(expiry_date__isnull=False, expiry_date__lte=timezone.now().date() + timedelta(days=45)).count(),
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="categories")
    def categories(self, request):
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        queryset = self.get_queryset()
        categories = list(queryset.exclude(category="").values_list("category", flat=True).distinct())
        default_categories = [
            "Antibiotics",
            "Analgesics",
            "Antihypertensives",
            "Vitamins",
            "Diabetes",
            "Cardiovascular",
            "Respiratory",
            "Dermatology",
            "Gastrointestinal",
            "Supplements",
        ]
        all_categories = sorted(list(set([c for c in categories if c] + default_categories)))
        return Response(all_categories, status=status.HTTP_200_OK)
