from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.reports.services import ReportService
from apps.sales.models import Sale
from apps.tenants.models import Tenant
from core.api.permissions import (
    CanViewFinancials,
    HasActiveSubscription,
    TenantMembershipPermission,
)


class DashboardViewSet(viewsets.ViewSet):
    permission_classes = (IsAuthenticated,)

    def get_permissions(self):
        if getattr(self, "action", None) == "super_admin":
            return [IsAuthenticated()]
        return [IsAuthenticated(), TenantMembershipPermission(), HasActiveSubscription()]

    def _get_tenant(self, request) -> Tenant:
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        try:
            return Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist as exc:
            raise ValidationError("Tenant not found.") from exc

    @action(detail=False, methods=["get"], url_path="owner")
    def owner(self, request):
        tenant = self._get_tenant(request)
        data = ReportService.get_overview(tenant=tenant, limit=8)
        data["recent_activities"] = data.pop("recent_activity", [])
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="pharmacist")
    def pharmacist(self, request):
        tenant = self._get_tenant(request)
        dashboard_stats = ReportService.get_dashboard_stats(tenant)
        alerts = ReportService.get_inventory_alerts(tenant=tenant, days=30)
        return Response(
            {
                "inventory_summary": dashboard_stats.get("inventory_summary", {}),
                "alerts": alerts,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="cashier")
    def cashier(self, request):
        tenant = self._get_tenant(request)
        dashboard_stats = ReportService.get_dashboard_stats(tenant)
        recent_sales = (
            Sale.unscoped.filter(
                tenant=tenant,
                status__in=[Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED],
            )
            .order_by("-created_at")[:5]
        )
        recent_transactions = [
            {
                "id": str(sale.id),
                "invoice_number": sale.invoice_number,
                "amount": str(sale.total_amount),
                "status": sale.status,
            }
            for sale in recent_sales
        ]
        return Response(
            {
                "today_sales": dashboard_stats.get("today", {}),
                "recent_transactions": recent_transactions,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="super-admin")
    def super_admin(self, request):
        return Response(
            {
                "platform_summary": {
                    "tenant_count": Tenant.objects.count(),
                    "active_tenant_count": Tenant.objects.filter(is_active=True).count(),
                    "recent_sales_count": Sale.unscoped.count(),
                }
            },
            status=status.HTTP_200_OK,
        )


class ReportViewSet(viewsets.ViewSet):
    """
    GET /api/v1/reports/dashboard/           — Overview KPI summary cards
    GET /api/v1/reports/financial/           — Financial breakdown (daily/weekly/monthly/yearly)
    GET /api/v1/reports/cashier-performance/ — Cashier sales ranking & performance
    GET /api/v1/reports/product-performance/ — Top & Slow medicines classification
    GET /api/v1/reports/inventory-valuation/ — Inventory asset valuation & stock stats
    GET /api/v1/reports/charts/              — Formatted time-series chart data
    """
    permission_classes = (IsAuthenticated, TenantMembershipPermission, HasActiveSubscription)

    def _get_tenant(self, request) -> Tenant:
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            raise ValidationError("X-Tenant-ID header is required.")
        try:
            return Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Tenant not found.")

    @action(detail=False, methods=["get"], url_path="dashboard")
    def dashboard(self, request):
        tenant = self._get_tenant(request)
        data = ReportService.get_dashboard_stats(tenant)
        return Response(data, status=status.HTTP_200_OK)

    @action(
        detail=False,
        methods=["get"],
        url_path="financial",
        permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanViewFinancials],
    )
    def financial(self, request):
        tenant = self._get_tenant(request)
        period = request.query_params.get("period", "monthly")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        data = ReportService.get_financial_report(
            tenant=tenant,
            period=period,
            start_date=start_date,
            end_date=end_date,
        )
        return Response(data, status=status.HTTP_200_OK)

    @action(
        detail=False,
        methods=["get"],
        url_path="cashier-performance",
        permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanViewFinancials],
    )
    def cashier_performance(self, request):
        tenant = self._get_tenant(request)
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        data = ReportService.get_cashier_performance(
            tenant=tenant,
            start_date=start_date,
            end_date=end_date,
        )
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="product-performance")
    def product_performance(self, request):
        tenant = self._get_tenant(request)
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        data = ReportService.get_product_performance(
            tenant=tenant,
            start_date=start_date,
            end_date=end_date,
        )
        return Response(data, status=status.HTTP_200_OK)

    @action(
        detail=False,
        methods=["get"],
        url_path="inventory-valuation",
        permission_classes=[IsAuthenticated, TenantMembershipPermission, HasActiveSubscription, CanViewFinancials],
    )
    def inventory_valuation(self, request):
        tenant = self._get_tenant(request)
        data = ReportService.get_inventory_valuation(tenant)
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="alerts")
    def alerts(self, request):
        tenant = self._get_tenant(request)
        days_param = request.query_params.get("days", "30")
        try:
            days = int(days_param)
        except (TypeError, ValueError):
            days = 30

        data = ReportService.get_inventory_alerts(tenant=tenant, days=days)
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="overview")
    def overview(self, request):
        tenant = self._get_tenant(request)
        limit_param = request.query_params.get("limit", "8")
        try:
            limit = int(limit_param)
        except (TypeError, ValueError):
            limit = 8

        data = ReportService.get_overview(tenant=tenant, limit=limit)
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="analytics")
    def analytics(self, request):
        tenant = self._get_tenant(request)
        period = request.query_params.get("period", "monthly")
        chart_type = request.query_params.get("chart_type", "revenue")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        branch = request.query_params.get("branch")
        warehouse = request.query_params.get("warehouse")
        supplier = request.query_params.get("supplier")
        customer = request.query_params.get("customer")
        cashier = request.query_params.get("cashier")
        product = request.query_params.get("product")
        category = request.query_params.get("category")
        status_param = request.query_params.get("status")
        search = request.query_params.get("search")
        ordering = request.query_params.get("ordering", "desc")
        limit_param = request.query_params.get("limit", "8")
        try:
            limit = int(limit_param)
        except (TypeError, ValueError):
            limit = 8

        data = ReportService.get_analytics(
            tenant=tenant,
            period=period,
            chart_type=chart_type,
            start_date=start_date,
            end_date=end_date,
            branch=branch,
            warehouse=warehouse,
            supplier=supplier,
            customer=customer,
            cashier=cashier,
            product=product,
            category=category,
            status=status_param,
            search=search,
            ordering=ordering,
            limit=limit,
        )
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="charts")
    def charts(self, request):
        tenant = self._get_tenant(request)
        period = request.query_params.get("period", "monthly")
        year_param = request.query_params.get("year")
        year = int(year_param) if year_param and year_param.isdigit() else None

        data = ReportService.get_charts_data(tenant=tenant, period=period, year=year)
        return Response(data, status=status.HTTP_200_OK)
