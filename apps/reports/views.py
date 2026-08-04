from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.reports.services import ReportService
from apps.tenants.models import Tenant
from core.api.permissions import (
    CanViewFinancials,
    HasActiveSubscription,
    TenantMembershipPermission,
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
