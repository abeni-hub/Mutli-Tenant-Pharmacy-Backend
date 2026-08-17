from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.sales.models import Prescription, Sale
from apps.sales.serializers import (
    PrescriptionSerializer,
    SaleCancelSerializer,
    SaleCreateSerializer,
    SaleDetailSerializer,
    SaleListSerializer,
    SaleRefundInputSerializer,
    SaleRefundSerializer,
)
from apps.sales.services import SaleService
from apps.tenants.models import Tenant
from core.api.permissions import (
    CanAccessSales,
    CanProcessSale,
    CanViewFinancials,
    HasActiveSubscription,
    IsOwner,
    TenantMembershipPermission,
)


class SaleViewSet(viewsets.ModelViewSet):
    """
    POST /api/v1/sales/               — Process checkout (multi-medicine, optional tax & discount)
    GET  /api/v1/sales/               — List sales history (search & filterable)
    GET  /api/v1/sales/{id}/           — Retrieve invoice detail
    GET  /api/v1/sales/{id}/receipt/   — Formatted printable receipt
    POST /api/v1/sales/{id}/cancel/    — Cancel sale & restore stock
    POST /api/v1/sales/{id}/refund/    — Refund item & restore stock
    GET  /api/v1/sales/report/         — Financial sales & profit report
    """
    permission_classes = (IsAuthenticated, TenantMembershipPermission, HasActiveSubscription)
    filterset_fields = ("payment_method", "status", "is_taxable")
    search_fields = ("invoice_number", "customer_name", "customer_phone", "cashier__email", "cashier__first_name", "cashier__last_name")
    ordering_fields = ("created_at", "total_amount", "total_profit")
    ordering = ("-created_at",)

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            return Sale.unscoped.none()
        return Sale.unscoped.select_related("cashier", "cancelled_by").prefetch_related("items__product", "items__batch", "refunds").filter(tenant_id=tenant_id)

    def get_permissions(self):
        if self.action in {"list", "retrieve", "create", "receipt", "daily_sales", "payment_summary", "sales_report"}:
            return [IsAuthenticated(), TenantMembershipPermission(), HasActiveSubscription(), CanAccessSales()]
        if self.action == "resume":
            return [IsAuthenticated(), TenantMembershipPermission(), HasActiveSubscription(), CanProcessSale()]
        if self.action in {"cancel", "refund"}:
            return [IsAuthenticated(), TenantMembershipPermission(), HasActiveSubscription(), IsOwner()]
        return [IsAuthenticated(), TenantMembershipPermission(), HasActiveSubscription()]

    def get_serializer_class(self):
        if self.action == "list":
            return SaleListSerializer
        elif self.action in ["retrieve", "create"]:
            return SaleDetailSerializer
        return SaleDetailSerializer

    def create(self, request, *args, **kwargs):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")

        serializer = SaleCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        items_input = []
        for raw_item in serializer.validated_data["items"]:
            items_input.append(
                {
                    "product_id": raw_item["product_id"].id if hasattr(raw_item["product_id"], "id") else raw_item["product_id"],
                    "quantity": raw_item["quantity"],
                    "batch_id": raw_item.get("batch_id"),
                    "discount_amount": raw_item.get("discount_amount", 0.0),
                    "discount_percent": raw_item.get("discount_percent", 0.0),
                }
            )

        sale = SaleService.create_sale(
            tenant=tenant,
            cashier=request.user,
            items_data=items_input,
            customer_name=serializer.validated_data.get("customer_name", ""),
            customer_phone=serializer.validated_data.get("customer_phone", ""),
            payment_method=serializer.validated_data.get("payment_method", Sale.PaymentMethod.CASH),
            payment_status=serializer.validated_data.get("payment_status", Sale.PaymentStatus.PENDING),
            sale_status=serializer.validated_data.get("sale_status", Sale.Status.COMPLETED),
            sale_source=serializer.validated_data.get("sale_source", Sale.SaleSource.POS),
            branch=serializer.validated_data.get("branch", ""),
            receipt_number=serializer.validated_data.get("receipt_number", ""),
            sale_reference=serializer.validated_data.get("sale_reference", ""),
            discount_amount=serializer.validated_data.get("discount_amount", 0.0),
            discount_percent=serializer.validated_data.get("discount_percent", 0.0),
            tax_rate=serializer.validated_data.get("tax_rate", 0.0),
            notes=serializer.validated_data.get("notes", ""),
            internal_remarks=serializer.validated_data.get("internal_remarks", ""),
            change_returned=serializer.validated_data.get("change_returned", 0.0),
            loyalty_points=serializer.validated_data.get("loyalty_points", 0),
        )

        return Response(
            SaleDetailSerializer(sale).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="receipt")
    def receipt(self, request, pk=None):
        sale = self.get_object()
        serializer = SaleDetailSerializer(sale)
        return Response(serializer.data["receipt"], status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="resume",
        permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanProcessSale],
    )
    def resume(self, request, pk=None):
        sale = SaleService.resume_sale(sale_id=pk, resumed_by=request.user)
        return Response(
            {
                "detail": "Held sale resumed successfully.",
                "sale": SaleDetailSerializer(sale).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="cancel",
        permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, IsOwner],
    )
    def cancel(self, request, pk=None):
        serializer = SaleCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        sale = SaleService.cancel_sale(
            sale_id=pk,
            cancelled_by=request.user,
            reason=serializer.validated_data["reason"],
        )
        return Response(
            {
                "detail": f"Sale invoice '{sale.invoice_number}' successfully cancelled and stock restored.",
                "sale": SaleDetailSerializer(sale).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="refund",
        permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, IsOwner],
    )
    def refund(self, request, pk=None):
        serializer = SaleRefundInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        refund = SaleService.refund_sale_item(
            sale_id=pk,
            item_id=serializer.validated_data["item_id"],
            quantity_to_refund=serializer.validated_data["quantity"],
            reason=serializer.validated_data["reason"],
            processed_by=request.user,
        )
        return Response(
            {
                "detail": f"Refund of ${refund.refund_amount} processed successfully.",
                "refund": SaleRefundSerializer(refund).data,
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="daily",
        permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanViewFinancials],
    )
    def daily_sales(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")

        return Response(
            SaleService.generate_daily_sales(tenant=tenant),
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="payment-summary",
        permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanViewFinancials],
    )
    def payment_summary(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")

        return Response(
            SaleService.generate_payment_summary(tenant=tenant),
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="report",
        permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanViewFinancials],
    )
    def sales_report(self, request):
        tenant_id = request.tenant_id
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")

        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        report_data = SaleService.generate_sales_report(
            tenant=tenant,
            start_date=start_date,
            end_date=end_date,
        )
        return Response(report_data, status=status.HTTP_200_OK)


class PrescriptionViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated, TenantMembershipPermission, HasActiveSubscription)
    serializer_class = PrescriptionSerializer
    filterset_fields = ("status", "branch")
    search_fields = ("rx_number", "customer_name", "doctor_name", "notes")
    ordering_fields = ("created_at", "date")
    ordering = ("-created_at",)

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            return Prescription.unscoped.none()
        return Prescription.unscoped.prefetch_related("items").filter(tenant_id=tenant_id)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["tenant_id"] = getattr(self.request, "tenant_id", None)
        return context

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        serializer.save(tenant_id=tenant_id, created_by=self.request.user)
