from django.db.models import F, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.inventory.models import InventoryLog, StockBatch
from apps.inventory.serializers import (
    InventoryLogSerializer,
    LowStockProductSerializer,
    StockAdjustmentSerializer,
    StockBatchSerializer,
    StockInSerializer,
    StockOutFIFOSerializer,
    TransferSerializer,
)
from apps.inventory.services import InventoryService
from apps.tenants.models import Tenant
from core.api.permissions import (
    CanManageInventory,
    CanProcessSale,
    HasActiveSubscription,
    TenantMembershipPermission,
)


class StockBatchViewSet(viewsets.ModelViewSet):
    """
    GET  /api/v1/inventory/batches/            — List stock batches
    POST /api/v1/inventory/batches/stock-in/   — Receive stock (Stock In)
    POST /api/v1/inventory/batches/stock-out-fifo/ — Deduct stock (FIFO Stock Out)
    POST /api/v1/inventory/batches/adjust/     — Adjust stock quantity
    GET  /api/v1/inventory/batches/expired/    — Query expired batches
    GET  /api/v1/inventory/batches/near-expiry/— Query near-expiry batches (default 60 days)
    GET  /api/v1/inventory/batches/low-stock/   — Query low-stock products (<= reorder_level)
    """
    permission_classes = (IsAuthenticated, TenantMembershipPermission, HasActiveSubscription)
    serializer_class = StockBatchSerializer
    filterset_fields = (
        "product",
        "batch_number",
        "lot_number",
        "supplier",
        "purchase_order_reference",
        "warehouse",
        "branch",
        "batch_status",
        "is_active",
    )
    search_fields = (
        "batch_number",
        "lot_number",
        "product__name",
        "product__sku",
        "supplier",
        "purchase_order_reference",
        "warehouse",
        "branch",
        "location",
        "notes",
    )
    ordering_fields = ("expiry_date", "quantity", "created_at", "unit_price", "selling_price", "purchase_date")

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            return StockBatch.objects.none()
        return (
            StockBatch.objects.select_related("product")
            .filter(tenant_id=tenant_id)
            .order_by("expiry_date", "created_at")
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="stock-in",
        permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanManageInventory],
    )
    def stock_in(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")

        serializer = StockInSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        batch = InventoryService.stock_in(
            tenant=tenant,
            product=serializer.validated_data["product_id"],
            batch_number=serializer.validated_data["batch_number"],
            quantity=serializer.validated_data["quantity"],
            expiry_date=serializer.validated_data["expiry_date"],
            unit_price=serializer.validated_data["unit_price"],
            selling_price=serializer.validated_data["selling_price"],
            manufacture_date=serializer.validated_data.get("manufacture_date"),
            purchase_date=serializer.validated_data.get("purchase_date"),
            supplier=serializer.validated_data.get("supplier", ""),
            purchase_order_reference=serializer.validated_data.get("purchase_order_reference", ""),
            warehouse=serializer.validated_data.get("warehouse", ""),
            branch=serializer.validated_data.get("branch", ""),
            location=serializer.validated_data.get("location", ""),
            reorder_level=serializer.validated_data.get("reorder_level", 0),
            reorder_quantity=serializer.validated_data.get("reorder_quantity", 0),
            notes=serializer.validated_data.get("notes", ""),
            batch_status=serializer.validated_data.get("batch_status", "active"),
            reference_number=serializer.validated_data.get("reference_number", ""),
            performed_by=request.user,
        )

        return Response(
            StockBatchSerializer(batch).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="stock-out-fifo",
        permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanProcessSale],
    )
    def stock_out_fifo(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")

        serializer = StockOutFIFOSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        deductions = InventoryService.stock_out_fifo(
            tenant=tenant,
            product=serializer.validated_data["product_id"],
            quantity=serializer.validated_data["quantity"],
            reason=serializer.validated_data.get("reason", "Sale Dispense"),
            reference_number=serializer.validated_data.get("reference_number", ""),
            batch_id=str(serializer.validated_data.get("batch_id")) if serializer.validated_data.get("batch_id") else None,
            performed_by=request.user,
        )

        return Response(
            {
                "detail": "FIFO stock deduction completed successfully.",
                "total_deducted": serializer.validated_data["quantity"],
                "deductions": deductions,
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="adjust",
        permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanManageInventory],
    )
    def adjust_stock(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")

        serializer = StockAdjustmentSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        batch = InventoryService.adjust_stock(
            tenant=tenant,
            batch=serializer.validated_data["batch_id"],
            new_quantity=serializer.validated_data["new_quantity"],
            reason=serializer.validated_data["reason"],
            reference_number=serializer.validated_data.get("reference_number", ""),
            performed_by=request.user,
        )

        return Response(
            StockBatchSerializer(batch).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="expired")
    def expired_batches(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")

        expired = InventoryService.get_expired_batches(tenant)
        return Response(StockBatchSerializer(expired, many=True).data)

    @action(detail=False, methods=["get"], url_path="near-expiry")
    def near_expiry_batches(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")

        days_param = request.query_params.get("days", "60")
        try:
            days = int(days_param)
        except ValueError:
            days = 60

        near_expiry = InventoryService.get_near_expiry_batches(tenant, threshold_days=days)
        return Response(StockBatchSerializer(near_expiry, many=True).data)

    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock_products(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")

        low_stock = InventoryService.get_low_stock_products(tenant)
        return Response(LowStockProductSerializer(low_stock, many=True).data)

    @action(detail=True, methods=["post"], url_path="transfer", permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanManageInventory])
    def transfer(self, request, pk=None):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")

        serializer = TransferSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        batch = self.get_queryset().filter(id=pk).first()
        if not batch:
            raise ValidationError("Batch not found.")

        batch = InventoryService.transfer_stock(
            tenant=tenant,
            batch=batch,
            quantity=serializer.validated_data["quantity"],
            destination=serializer.validated_data["destination"],
            reason=serializer.validated_data.get("reason", "Transfer"),
            reference_number=serializer.validated_data.get("reference_number", ""),
            performed_by=request.user,
        )
        return Response(StockBatchSerializer(batch).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")
        return Response(InventoryService.get_inventory_summary(tenant), status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="valuation")
    def valuation(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")
        return Response(InventoryService.get_inventory_valuation(tenant), status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")
        batch = self.get_queryset().filter(id=pk).first()
        if not batch:
            raise ValidationError("Batch not found.")
        history = InventoryService.get_batch_history(tenant, batch)
        return Response(InventoryLogSerializer(history, many=True).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")
        batch = self.get_queryset().filter(id=pk).first()
        if not batch:
            raise ValidationError("Batch not found.")
        batch = InventoryService.archive_batch(tenant=tenant, batch=batch, reason=request.data.get("reason", "Archived"), performed_by=request.user)
        return Response(StockBatchSerializer(batch).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")
        batch = self.get_queryset().filter(id=pk).first()
        if not batch:
            raise ValidationError("Batch not found.")
        batch = InventoryService.restore_batch(tenant=tenant, batch=batch, performed_by=request.user)
        return Response(StockBatchSerializer(batch).data, status=status.HTTP_200_OK)


class InventoryLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/v1/inventory/logs/       — List inventory movement audit logs
    GET /api/v1/inventory/logs/{id}/  — Retrieve single inventory log
    """
    permission_classes = (IsAuthenticated, TenantMembershipPermission)
    serializer_class = InventoryLogSerializer
    filterset_fields = ("product", "batch", "transaction_type")
    search_fields = ("reference_number", "reason", "product__name", "product__sku", "batch__batch_number")
    ordering_fields = ("created_at", "quantity_changed")
    ordering = ("-created_at",)

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            return InventoryLog.objects.none()
        return InventoryLog.objects.select_related("product", "batch", "performed_by").filter(tenant_id=tenant_id)
