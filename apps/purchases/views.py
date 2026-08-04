from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.purchases.models import GoodsReceipt, PurchaseOrder, PurchaseOrderItem, Supplier
from apps.purchases.serializers import (
    GoodsReceiptSerializer,
    PurchaseOrderCreateSerializer,
    PurchaseOrderSerializer,
    PurchaseReceiveSerializer,
    SupplierSerializer,
)
from apps.purchases.services import PurchaseService
from apps.tenants.models import Tenant
from core.api.permissions import (
    CanManageInventory,
    CanViewFinancials,
    HasActiveSubscription,
    IsOwnerOrManager,
    TenantMembershipPermission,
)


class SupplierViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated, TenantMembershipPermission, HasActiveSubscription)
    serializer_class = SupplierSerializer
    filterset_fields = ("status", "preferred_supplier", "is_active")
    search_fields = ("code", "company_name", "contact_person", "email", "phone")
    ordering_fields = ("company_name", "created_at", "status")
    ordering = ("company_name",)

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            return Supplier.unscoped.none()
        return Supplier.unscoped.filter(tenant_id=tenant_id)

    def create(self, request, *args, **kwargs):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        tenant = Tenant.objects.get(id=tenant_id)
        serializer = SupplierSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        supplier = Supplier.objects.create(tenant=tenant, **serializer.validated_data)
        return Response(SupplierSerializer(supplier).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        supplier = self.get_object()
        supplier.is_active = False
        supplier.status = Supplier.Status.ARCHIVED
        supplier.save(update_fields=["is_active", "status"])
        return Response(SupplierSerializer(supplier).data)

    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        supplier = self.get_object()
        supplier.is_active = True
        supplier.status = Supplier.Status.ACTIVE
        supplier.save(update_fields=["is_active", "status"])
        return Response(SupplierSerializer(supplier).data)


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated, TenantMembershipPermission, HasActiveSubscription)
    serializer_class = PurchaseOrderSerializer
    filterset_fields = ("status", "supplier", "branch", "warehouse")
    search_fields = ("po_number", "supplier__company_name", "notes")
    ordering_fields = ("created_at", "total", "expected_delivery")
    ordering = ("-created_at",)

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            return PurchaseOrder.unscoped.none()
        return (
            PurchaseOrder.unscoped.select_related("supplier")
            .prefetch_related("items__product")
            .filter(tenant_id=tenant_id)
        )

    def create(self, request, *args, **kwargs):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        tenant = Tenant.objects.get(id=tenant_id)
        serializer = PurchaseOrderCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        purchase_order = PurchaseService.create_purchase(
            tenant=tenant,
            supplier=serializer.validated_data["supplier"],
            data={
                "po_number": serializer.validated_data["po_number"],
                "branch": serializer.validated_data.get("branch", ""),
                "warehouse": serializer.validated_data.get("warehouse", ""),
                "expected_delivery": serializer.validated_data.get("expected_delivery"),
                "notes": serializer.validated_data.get("notes", ""),
                "status": serializer.validated_data.get("status", PurchaseOrder.Status.DRAFT),
                "discount": serializer.validated_data.get("discount", 0),
                "tax": serializer.validated_data.get("tax", 0),
                "items": [
                    {
                        "product": item["product"],
                        "ordered_quantity": item["ordered_quantity"],
                        "unit_cost": item.get("unit_cost", 0),
                        "discount": item.get("discount", 0),
                        "tax": item.get("tax", 0),
                    }
                    for item in serializer.validated_data["items"]
                ],
            },
            performed_by=request.user,
        )
        return Response(PurchaseOrderSerializer(purchase_order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="approve", permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, IsOwnerOrManager])
    def approve(self, request, pk=None):
        purchase_order = self.get_object()
        purchase_order = PurchaseService.approve_purchase(purchase_order=purchase_order, performed_by=request.user)
        return Response(PurchaseOrderSerializer(purchase_order).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="receive", permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanManageInventory])
    def receive(self, request, pk=None):
        serializer = PurchaseReceiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        purchase_order = self.get_object()
        purchase_order = PurchaseService.receive_purchase(
            purchase_order=purchase_order,
            complete=serializer.validated_data.get("complete", True),
            notes=serializer.validated_data.get("notes", ""),
            performed_by=request.user,
        )
        return Response(PurchaseOrderSerializer(purchase_order).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="cancel", permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, IsOwnerOrManager])
    def cancel(self, request, pk=None):
        purchase_order = self.get_object()
        purchase_order = PurchaseService.cancel_purchase(purchase_order=purchase_order, reason="", performed_by=request.user)
        return Response(PurchaseOrderSerializer(purchase_order).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="summary", permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanViewFinancials])
    def summary(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        tenant = Tenant.objects.get(id=tenant_id)
        return Response(PurchaseService.get_summary(tenant), status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="supplier-performance", permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanViewFinancials])
    def supplier_performance(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        tenant = Tenant.objects.get(id=tenant_id)
        return Response(PurchaseService.get_supplier_performance(tenant), status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="trends", permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanViewFinancials])
    def trends(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        tenant = Tenant.objects.get(id=tenant_id)
        return Response(PurchaseService.get_trends(tenant), status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="costs", permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanViewFinancials])
    def costs(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        tenant = Tenant.objects.get(id=tenant_id)
        return Response(PurchaseService.get_purchase_costs(tenant), status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="outstanding", permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanViewFinancials])
    def outstanding(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        tenant = Tenant.objects.get(id=tenant_id)
        return Response(PurchaseService.get_outstanding_purchase_orders(tenant), status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="received", permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanViewFinancials])
    def received(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        tenant = Tenant.objects.get(id=tenant_id)
        return Response(PurchaseService.get_received_orders(tenant), status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="supplier-spend", permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanViewFinancials])
    def supplier_spend(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        tenant = Tenant.objects.get(id=tenant_id)
        return Response(PurchaseService.get_supplier_spend(tenant), status=status.HTTP_200_OK)


class GoodsReceiptViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (IsAuthenticated, TenantMembershipPermission, HasActiveSubscription)
    serializer_class = GoodsReceiptSerializer
    filterset_fields = ("complete", "purchase_order")
    search_fields = ("receipt_number", "notes")
    ordering_fields = ("received_at",)

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            return GoodsReceipt.unscoped.none()
        return GoodsReceipt.unscoped.select_related("purchase_order", "batch").filter(tenant_id=tenant_id)
