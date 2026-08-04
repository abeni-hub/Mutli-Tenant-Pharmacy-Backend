"""
Report service layer.

Handles Dashboard KPI statistics, Period-based financial reports (Daily, Weekly, Monthly, Yearly),
Cashier performance, Top & Slow medicines classification, Inventory valuation, and Charts API data.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db.models import Count, F, ExpressionWrapper, DecimalField, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek, TruncYear
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.catalog.models import Product
from apps.inventory.models import StockBatch
from apps.purchases.models import PurchaseOrder
from apps.sales.models import Sale, SaleItem

if TYPE_CHECKING:
    from apps.tenants.models import Tenant


class ReportService:
    @staticmethod
    def get_dashboard_stats(tenant: Tenant) -> dict[str, Any]:
        """Return high-level summary KPI cards for tenant dashboard."""
        today = timezone.now().date()
        first_of_month = today.replace(day=1)

        # Sales Querysets
        completed_sales = Sale.unscoped.filter(
            tenant=tenant,
            status__in=[Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED],
        )

        today_sales = completed_sales.filter(created_at__date=today)
        month_sales = completed_sales.filter(created_at__date__gte=first_of_month)

        today_agg = today_sales.aggregate(
            rev=Sum("total_amount"), profit=Sum("total_profit"), count=Count("id"), cost=Sum("total_cost")
        )
        month_agg = month_sales.aggregate(
            rev=Sum("total_amount"), profit=Sum("total_profit"), count=Count("id"), cost=Sum("total_cost")
        )

        # Inventory Stats
        active_products_count = Product.unscoped.filter(tenant=tenant, is_active=True).count()

        total_stock_balance_count = StockBatch.unscoped.filter(
            tenant=tenant, is_active=True, quantity__gt=0, expiry_date__gt=today
        ).aggregate(total=Sum("quantity"))["total"] or 0

        # Low Stock count
        products = Product.unscoped.filter(tenant=tenant, is_active=True)
        low_stock_count = 0
        for p in products:
            total_stock = (
                StockBatch.unscoped.filter(
                    tenant=tenant,
                    product=p,
                    is_active=True,
                    quantity__gt=0,
                    expiry_date__gt=today,
                ).aggregate(total=Sum("quantity"))["total"]
                or 0
            )
            if total_stock <= p.reorder_level:
                low_stock_count += 1

        # Expired & Near Expiry Batches
        expired_batches_count = StockBatch.unscoped.filter(
            tenant=tenant, is_active=True, quantity__gt=0, expiry_date__lte=today
        ).count()

        near_expiry_threshold = today + timedelta(days=60)
        near_expiry_batches_count = StockBatch.unscoped.filter(
            tenant=tenant,
            is_active=True,
            quantity__gt=0,
            expiry_date__gt=today,
            expiry_date__lte=near_expiry_threshold,
        ).count()

        return {
            "today": {
                "revenue": str(today_agg["rev"] or Decimal("0.00")),
                "cost": str(today_agg["cost"] or Decimal("0.00")),
                "profit": str(today_agg["profit"] or Decimal("0.00")),
                "net_profit": str(today_agg["profit"] or Decimal("0.00")),
                "sales_count": today_agg["count"] or 0,
            },
            "this_month": {
                "revenue": str(month_agg["rev"] or Decimal("0.00")),
                "cost": str(month_agg["cost"] or Decimal("0.00")),
                "profit": str(month_agg["profit"] or Decimal("0.00")),
                "net_profit": str(month_agg["profit"] or Decimal("0.00")),
                "sales_count": month_agg["count"] or 0,
            },
            "inventory_summary": {
                "active_products": active_products_count,
                "active_products_count": active_products_count,
                "total_stock_balance": total_stock_balance_count,
                "total_stock_balance_count": total_stock_balance_count,
                "low_stock_products": low_stock_count,
                "low_stock_products_count": low_stock_count,
                "expired_batches": expired_batches_count,
                "expired_batches_count": expired_batches_count,
                "near_expiry_batches": near_expiry_batches_count,
                "near_expiry_batches_count": near_expiry_batches_count,
            },
        }

    @staticmethod
    def get_financial_report(
        tenant: Tenant,
        period: str = "monthly",
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[str, Any]:
        """
        Period-based financial breakdown (daily, weekly, monthly, yearly).
        """
        qs = Sale.unscoped.filter(
            tenant=tenant,
            status__in=[Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED],
        )

        if start_date:
            qs = qs.filter(created_at__date__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__date__lte=end_date)

        if period == "daily":
            trunc_func = TruncDay("created_at")
        elif period == "weekly":
            trunc_func = TruncWeek("created_at")
        elif period == "yearly":
            trunc_func = TruncYear("created_at")
        else:
            trunc_func = TruncMonth("created_at")

        records = (
            qs.annotate(period_key=trunc_func)
            .values("period_key")
            .annotate(
                revenue=Sum("total_amount"),
                cogs=Sum("total_cost"),
                profit=Sum("total_profit"),
                tax_collected=Sum("tax_amount"),
                discounts_given=Sum("discount_amount"),
                sales_count=Count("id"),
            )
            .order_by("period_key")
        )

        breakdown = []
        for r in records:
            p_date = r["period_key"]
            date_label = p_date.strftime("%Y-%m-%d") if p_date else "Unknown"
            breakdown.append(
                {
                    "date_period": date_label,
                    "sales_count": r["sales_count"],
                    "revenue": str(r["revenue"] or Decimal("0.00")),
                    "cogs": str(r["cogs"] or Decimal("0.00")),
                    "profit": str(r["profit"] or Decimal("0.00")),
                    "tax_collected": str(r["tax_collected"] or Decimal("0.00")),
                    "discounts_given": str(r["discounts_given"] or Decimal("0.00")),
                }
            )

        totals = qs.aggregate(
            total_rev=Sum("total_amount"),
            total_cogs=Sum("total_cost"),
            total_profit=Sum("total_profit"),
            total_tax=Sum("tax_amount"),
            total_disc=Sum("discount_amount"),
            total_count=Count("id"),
        )

        return {
            "period_type": period,
            "totals": {
                "total_sales_count": totals["total_count"] or 0,
                "total_revenue": str(totals["total_rev"] or Decimal("0.00")),
                "total_cogs": str(totals["total_cogs"] or Decimal("0.00")),
                "total_profit": str(totals["total_profit"] or Decimal("0.00")),
                "total_tax_collected": str(totals["total_tax"] or Decimal("0.00")),
                "total_discounts_given": str(totals["total_disc"] or Decimal("0.00")),
            },
            "breakdown": breakdown,
        }

    @staticmethod
    def get_cashier_performance(
        tenant: Tenant,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        """Cashier sales ranking & performance analysis."""
        qs = Sale.unscoped.filter(
            tenant=tenant,
            status__in=[Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED],
        )

        if start_date:
            qs = qs.filter(created_at__date__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__date__lte=end_date)

        records = (
            qs.values(
                "cashier__id",
                "cashier__email",
                "cashier__first_name",
                "cashier__last_name",
            )
            .annotate(
                sales_count=Count("id"),
                total_revenue=Sum("total_amount"),
                total_profit=Sum("total_profit"),
            )
            .order_by("-total_revenue")
        )

        result = []
        for r in records:
            count = r["sales_count"] or 0
            rev = r["total_revenue"] or Decimal("0.00")
            prof = r["total_profit"] or Decimal("0.00")
            avg_val = round(rev / Decimal(str(count)), 2) if count > 0 else Decimal("0.00")
            full_name = f"{r['cashier__first_name']} {r['cashier__last_name']}".strip() or r["cashier__email"]

            result.append(
                {
                    "cashier_id": r["cashier__id"],
                    "name": full_name,
                    "cashier_name": full_name,
                    "email": r["cashier__email"],
                    "cashier_email": r["cashier__email"],
                    "sales_count": count,
                    "total_revenue": str(rev),
                    "total_profit": str(prof),
                    "average_sale_value": str(avg_val),
                }
            )

        return result

    @staticmethod
    def get_product_performance(
        tenant: Tenant,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Classify products into Top Selling vs Slow Moving Medicines."""
        sale_qs = Sale.unscoped.filter(
            tenant=tenant,
            status__in=[Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED],
        )
        if start_date:
            sale_qs = sale_qs.filter(created_at__date__gte=start_date)
        if end_date:
            sale_qs = sale_qs.filter(created_at__date__lte=end_date)

        # Top Medicines (highest quantity sold)
        top_qs = (
            SaleItem.unscoped.filter(sale__tenant=tenant, sale__in=sale_qs)
            .values("product__id", "product__name", "product__sku")
            .annotate(
                total_quantity_sold=Sum("quantity"),
                total_revenue=Sum("total_price"),
                total_profit=Sum("profit"),
            )
            .order_by("-total_quantity_sold")[:limit]
        )

        top_medicines = [
            {
                "product_id": item["product__id"],
                "product_name": item["product__name"],
                "sku": item["product__sku"],
                "quantity_sold": item["total_quantity_sold"],
                "total_revenue": str(item["total_revenue"] or Decimal("0.00")),
                "total_profit": str(item["total_profit"] or Decimal("0.00")),
            }
            for item in top_qs
        ]

        # Slow Medicines (Active products with zero or lowest sales)
        sold_product_ids = (
            SaleItem.unscoped.filter(sale__tenant=tenant, sale__in=sale_qs)
            .values_list("product__id", flat=True)
            .distinct()
        )

        slow_products = Product.unscoped.filter(
            tenant=tenant, is_active=True
        ).exclude(id__in=sold_product_ids)[:limit]

        slow_medicines = [
            {
                "product_id": p.id,
                "product_name": p.name,
                "sku": p.sku,
                "total_stock": p.total_stock,
                "quantity_sold": 0,
                "status": "Zero Sales / Slow Moving",
            }
            for p in slow_products
        ]

        return {
            "top_medicines": top_medicines,
            "slow_medicines": slow_medicines,
        }

    @staticmethod
    def get_inventory_valuation(tenant: Tenant) -> dict[str, Any]:
        """Return financial asset valuation of current non-expired inventory."""
        today = timezone.now().date()
        batches = StockBatch.unscoped.filter(
            tenant=tenant,
            is_active=True,
            quantity__gt=0,
            expiry_date__gt=today,
        )

        cost_expr = ExpressionWrapper(
            F("quantity") * F("unit_price"), output_field=DecimalField(max_digits=12, decimal_places=2)
        )
        retail_expr = ExpressionWrapper(
            F("quantity") * F("selling_price"), output_field=DecimalField(max_digits=12, decimal_places=2)
        )

        valuation = batches.aggregate(
            total_cost=Sum(cost_expr),
            total_retail=Sum(retail_expr),
            total_items=Sum("quantity"),
            total_batches=Count("id"),
        )

        cost_val = valuation["total_cost"] or Decimal("0.00")
        retail_val = valuation["total_retail"] or Decimal("0.00")
        potential_profit = retail_val - cost_val
        margin = round((potential_profit / retail_val * Decimal("100")), 2) if retail_val > Decimal("0.00") else Decimal("0.00")

        return {
            "total_active_batches": valuation["total_batches"] or 0,
            "total_items_in_stock": valuation["total_items"] or 0,
            "cost_valuation": str(cost_val),
            "retail_valuation": str(retail_val),
            "potential_profit": str(potential_profit),
            "potential_profit_margin": f"{margin}%",
        }

    @staticmethod
    def get_inventory_alerts(tenant: Tenant, days: int = 30) -> dict[str, Any]:
        """Return inventory risk alerts for low stock and near-expiry batches."""
        today = timezone.now().date()
        threshold_date = today + timedelta(days=days)

        products = Product.unscoped.filter(tenant=tenant, is_active=True)
        low_stock = []
        for product in products:
            total_stock = (
                StockBatch.unscoped.filter(
                    tenant=tenant,
                    product=product,
                    is_active=True,
                    quantity__gt=0,
                    expiry_date__gt=today,
                ).aggregate(total=Sum("quantity"))["total"]
                or 0
            )
            if total_stock <= product.reorder_level:
                low_stock.append(
                    {
                        "product_id": product.id,
                        "product_name": product.name,
                        "sku": product.sku,
                        "current_stock": total_stock,
                        "reorder_level": product.reorder_level,
                        "status": "Low Stock",
                    }
                )

        near_expiry = []
        batches = StockBatch.unscoped.filter(
            tenant=tenant,
            is_active=True,
            quantity__gt=0,
            expiry_date__gt=today,
            expiry_date__lte=threshold_date,
        ).order_by("expiry_date")

        for batch in batches:
            near_expiry.append(
                {
                    "batch_id": batch.id,
                    "batch_number": batch.batch_number,
                    "product_id": batch.product.id,
                    "product_name": batch.product.name,
                    "sku": batch.product.sku,
                    "quantity": batch.quantity,
                    "expiry_date": batch.expiry_date,
                    "days_to_expiry": (batch.expiry_date - today).days,
                }
            )

        return {
            "low_stock": low_stock,
            "near_expiry": near_expiry,
            "window_days": days,
        }

    @staticmethod
    def get_overview(tenant: Tenant, limit: int = 8) -> dict[str, Any]:
        """Return dashboard-card style overview data for enterprise reporting."""
        today = timezone.now().date()
        first_of_month = today.replace(day=1)

        completed_sales = Sale.unscoped.filter(
            tenant=tenant,
            status__in=[Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED],
        )
        month_sales = completed_sales.filter(created_at__date__gte=first_of_month)

        prev_month_end = first_of_month - timedelta(days=1)
        if prev_month_end.month == 12:
            prev_month_start = date(prev_month_end.year - 1, 12, 1)
        else:
            prev_month_start = date(prev_month_end.year, prev_month_end.month, 1)
        prev_sales = completed_sales.filter(created_at__date__gte=prev_month_start, created_at__date__lte=prev_month_end)

        month_agg = month_sales.aggregate(
            rev=Sum("total_amount"),
            profit=Sum("total_profit"),
            count=Count("id"),
            cost=Sum("total_cost"),
        )
        prev_agg = prev_sales.aggregate(
            rev=Sum("total_amount"),
            profit=Sum("total_profit"),
            count=Count("id"),
        )

        def as_decimal(value: Any) -> Decimal:
            return value if isinstance(value, Decimal) else Decimal(str(value or "0"))

        def trend_percent(current: Decimal, previous: Decimal) -> float:
            if previous == 0:
                return 100.0 if current > 0 else 0.0
            return round(float(((current - previous) / previous) * Decimal("100")), 1)

        revenue_current = as_decimal(month_agg["rev"])
        revenue_previous = as_decimal(prev_agg["rev"])
        profit_current = as_decimal(month_agg["profit"])
        profit_previous = as_decimal(prev_agg["profit"])
        sales_current = int(month_agg["count"] or 0)
        sales_previous = int(prev_agg["count"] or 0)

        inventory_summary = ReportService.get_inventory_valuation(tenant)
        low_stock_summary = ReportService.get_inventory_alerts(tenant=tenant, days=30)
        purchase_orders = PurchaseOrder.unscoped.filter(tenant=tenant).exclude(status=PurchaseOrder.Status.CANCELLED)
        purchase_total = purchase_orders.aggregate(total=Sum("total"))["total"] or Decimal("0.00")

        kpis = [
            {
                "id": "revenue",
                "label": "Revenue",
                "value": str(revenue_current),
                "previous_value": str(revenue_previous),
                "trend": trend_percent(revenue_current, revenue_previous),
                "format": "currency",
                "icon": "DollarSign",
                "accent": "success",
            },
            {
                "id": "profit",
                "label": "Profit",
                "value": str(profit_current),
                "previous_value": str(profit_previous),
                "trend": trend_percent(profit_current, profit_previous),
                "format": "currency",
                "icon": "TrendingUp",
                "accent": "success",
            },
            {
                "id": "sales",
                "label": "Sales",
                "value": sales_current,
                "previous_value": sales_previous,
                "trend": trend_percent(Decimal(sales_current), Decimal(sales_previous)),
                "format": "number",
                "icon": "ShoppingBag",
                "accent": "primary",
            },
            {
                "id": "purchases",
                "label": "Purchases",
                "value": str(purchase_total),
                "previous_value": "0.00",
                "trend": 0.0,
                "format": "currency",
                "icon": "Package",
                "accent": "info",
            },
            {
                "id": "inventory",
                "label": "Inventory Value",
                "value": inventory_summary["cost_valuation"],
                "previous_value": inventory_summary["cost_valuation"],
                "trend": 0.0,
                "format": "currency",
                "icon": "Boxes",
                "accent": "info",
            },
            {
                "id": "stock",
                "label": "Low Stock Items",
                "value": len(low_stock_summary["low_stock"]),
                "previous_value": 0,
                "trend": 0.0,
                "format": "number",
                "icon": "AlertTriangle",
                "accent": "warning",
            },
        ]

        widgets = [
            {"id": "revenue", "label": "Revenue", "value": str(revenue_current), "format": "currency"},
            {"id": "profit", "label": "Profit", "value": str(profit_current), "format": "currency"},
            {"id": "inventory", "label": "Inventory", "value": inventory_summary["cost_valuation"], "format": "currency"},
            {"id": "purchases", "label": "Purchases", "value": str(purchase_total), "format": "currency"},
            {"id": "low_stock", "label": "Low Stock", "value": len(low_stock_summary["low_stock"]), "format": "number"},
        ]

        recent_activity_items = []
        for sale in completed_sales.order_by("-created_at")[:3]:
            recent_activity_items.append(
                {
                    "id": f"sale-{sale.id}",
                    "type": "sale",
                    "title": f"Sale {sale.invoice_number}",
                    "meta": f"{sale.total_amount}",
                    "created_at": sale.created_at.isoformat(),
                }
            )
        for purchase in purchase_orders.order_by("-created_at")[:2]:
            recent_activity_items.append(
                {
                    "id": f"purchase-{purchase.id}",
                    "type": "purchase",
                    "title": purchase.po_number,
                    "meta": purchase.status,
                    "created_at": purchase.created_at.isoformat(),
                }
            )
        for audit_event in AuditEvent.objects.filter(tenant=tenant).order_by("-created_at")[:3]:
            recent_activity_items.append(
                {
                    "id": f"audit-{audit_event.id}",
                    "type": "audit",
                    "title": audit_event.entity_type,
                    "meta": audit_event.action,
                    "created_at": audit_event.created_at.isoformat(),
                }
            )

        recent_activity = sorted(recent_activity_items, key=lambda item: item["created_at"], reverse=True)[:limit]

        return {
            "kpis": kpis,
            "widgets": widgets,
            "recent_activity": recent_activity,
        }

    @staticmethod
    def get_analytics(
        tenant: Tenant,
        period: str = "monthly",
        chart_type: str = "revenue",
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        branch: str | None = None,
        warehouse: str | None = None,
        supplier: str | None = None,
        customer: str | None = None,
        cashier: str | None = None,
        product: str | None = None,
        category: str | None = None,
        status: str | None = None,
        search: str | None = None,
        ordering: str = "desc",
        limit: int = 8,
    ) -> dict[str, Any]:
        """Return analytics payload with summary, trend data, and product rankings."""
        sale_qs = Sale.unscoped.filter(
            tenant=tenant,
            status__in=[Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED],
        )
        sale_item_qs = SaleItem.unscoped.filter(sale__tenant=tenant, sale__in=sale_qs)

        if start_date:
            sale_qs = sale_qs.filter(created_at__date__gte=start_date)
            sale_item_qs = sale_item_qs.filter(sale__created_at__date__gte=start_date)
        if end_date:
            sale_qs = sale_qs.filter(created_at__date__lte=end_date)
            sale_item_qs = sale_item_qs.filter(sale__created_at__date__lte=end_date)
        if branch:
            sale_qs = sale_qs.filter(branch__icontains=branch)
        if warehouse:
            sale_qs = sale_qs.filter(branch__icontains=warehouse)
        if customer:
            sale_qs = sale_qs.filter(Q(customer_name__icontains=customer) | Q(customer_phone__icontains=customer))
        if cashier:
            sale_qs = sale_qs.filter(
                Q(cashier__email__icontains=cashier)
                | Q(cashier__first_name__icontains=cashier)
                | Q(cashier__last_name__icontains=cashier)
            )
        if status:
            sale_qs = sale_qs.filter(status=status)
        if search:
            sale_qs = sale_qs.filter(
                Q(invoice_number__icontains=search)
                | Q(receipt_number__icontains=search)
                | Q(customer_name__icontains=search)
                | Q(branch__icontains=search)
                | Q(notes__icontains=search)
            )
            sale_item_qs = sale_item_qs.filter(
                Q(product__name__icontains=search) | Q(product__sku__icontains=search)
            )
        if product:
            sale_item_qs = sale_item_qs.filter(Q(product__name__icontains=product) | Q(product__sku__icontains=product))
            matching_sale_ids = sale_item_qs.values_list("sale_id", flat=True).distinct()
            sale_qs = sale_qs.filter(id__in=matching_sale_ids)
        if category:
            sale_item_qs = sale_item_qs.filter(product__category__icontains=category)
            matching_sale_ids = sale_item_qs.values_list("sale_id", flat=True).distinct()
            sale_qs = sale_qs.filter(id__in=matching_sale_ids)

        summary = sale_qs.aggregate(
            sales_count=Count("id"),
            revenue=Sum("total_amount"),
            profit=Sum("total_profit"),
            cost=Sum("total_cost"),
            tax=Sum("tax_amount"),
            discount=Sum("discount_amount"),
        )
        sales_count = int(summary["sales_count"] or 0)
        revenue_total = summary["revenue"] or Decimal("0.00")
        profit_total = summary["profit"] or Decimal("0.00")
        cost_total = summary["cost"] or Decimal("0.00")

        order = "-total_revenue" if ordering == "desc" else "total_revenue"
        top_products = (
            sale_item_qs.values("product__id", "product__name", "product__sku")
            .annotate(
                total_units=Sum("quantity"),
                total_revenue=Sum("total_price"),
                total_profit=Sum("profit"),
            )
            .order_by(order)[:limit]
        )

        sold_product_ids = sale_item_qs.values_list("product__id", flat=True).distinct()
        slow_moving_products = list(
            Product.unscoped.filter(tenant=tenant, is_active=True).exclude(id__in=sold_product_ids)[:limit]
        )

        trend_data = []
        trend_labels = []
        if period == "monthly":
            trend_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            trend_series = [Decimal("0.00")] * 12
            records = (
                sale_qs.annotate(period_key=TruncMonth("created_at"))
                .values("period_key")
                .annotate(value=Sum("total_amount"))
                .order_by("period_key")
            )
            for record in records:
                if record["period_key"]:
                    trend_series[record["period_key"].month - 1] = record["value"] or Decimal("0.00")
            for idx, value in enumerate(trend_series):
                trend_data.append(str(value))
        else:
            trend_labels = ["Today", "Yesterday", "2d", "3d", "4d", "5d", "6d"]
            trend_series = []
            for idx in range(6, -1, -1):
                day_date = timezone.now().date() - timedelta(days=idx)
                day_sales = sale_qs.filter(created_at__date=day_date).aggregate(value=Sum("total_amount"))
                trend_series.append(str(day_sales["value"] or Decimal("0.00")))
            trend_data = trend_series

        metric_name = chart_type if chart_type in {"revenue", "profit", "sales"} else "revenue"
        if metric_name == "profit":
            trend_series_values = [str(profit_total)]
            trend_labels = ["Total"]
            trend_data = [str(profit_total)]
        elif metric_name == "sales":
            trend_series_values = [str(sales_count)]
            trend_labels = ["Total"]
            trend_data = [str(sales_count)]
        else:
            trend_series_values = trend_data

        return {
            "summary": {
                "sales_count": sales_count,
                "revenue": str(revenue_total),
                "profit": str(profit_total),
                "cost": str(cost_total),
                "average_sale_value": str(revenue_total / Decimal(sales_count) if sales_count else Decimal("0.00")),
            },
            "trend": {
                "period": period,
                "labels": trend_labels,
                "datasets": {
                    "metric": metric_name,
                    "data": trend_series_values,
                },
            },
            "top_products": [
                {
                    "product_id": item["product__id"],
                    "product_name": item["product__name"],
                    "sku": item["product__sku"],
                    "total_units": item["total_units"],
                    "total_revenue": str(item["total_revenue"] or Decimal("0.00")),
                    "total_profit": str(item["total_profit"] or Decimal("0.00")),
                }
                for item in top_products
            ],
            "slow_moving_products": [
                {
                    "product_id": product_item.id,
                    "product_name": product_item.name,
                    "sku": product_item.sku,
                    "status": "Slow moving",
                }
                for product_item in slow_moving_products
            ],
        }

    @staticmethod
    def get_charts_data(
        tenant: Tenant,
        period: str = "monthly",
        year: int | None = None,
    ) -> dict[str, Any]:
        """
        Time-series dataset formatted for frontend charts (ApexCharts / Chart.js).
        """
        current_year = year or timezone.now().year
        qs = Sale.unscoped.filter(
            tenant=tenant,
            status__in=[Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED],
            created_at__year=current_year,
        )

        if period == "monthly":
            months_labels = [
                "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
            ]
            revenue_series = [Decimal("0.00")] * 12
            profit_series = [Decimal("0.00")] * 12
            count_series = [0] * 12

            records = (
                qs.annotate(m=TruncMonth("created_at"))
                .values("m")
                .annotate(
                    rev=Sum("total_amount"),
                    prof=Sum("total_profit"),
                    cnt=Count("id"),
                )
            )

            for r in records:
                if r["m"]:
                    idx = r["m"].month - 1
                    revenue_series[idx] = r["rev"] or Decimal("0.00")
                    profit_series[idx] = r["prof"] or Decimal("0.00")
                    count_series[idx] = r["cnt"] or 0

            return {
                "period": "monthly",
                "year": current_year,
                "labels": months_labels,
                "datasets": {
                    "revenue": [str(x) for x in revenue_series],
                    "profit": [str(x) for x in profit_series],
                    "sales_count": count_series,
                },
            }
        else:
            # Last 7 days breakdown
            today = timezone.now().date()
            days_labels = []
            revenue_series = []
            profit_series = []
            count_series = []

            for i in range(6, -1, -1):
                day_date = today - timedelta(days=i)
                days_labels.append(day_date.strftime("%a (%b %d)"))
                day_sales = qs.filter(created_at__date=day_date).aggregate(
                    rev=Sum("total_amount"), prof=Sum("total_profit"), cnt=Count("id")
                )
                revenue_series.append(str(day_sales["rev"] or Decimal("0.00")))
                profit_series.append(str(day_sales["prof"] or Decimal("0.00")))
                count_series.append(day_sales["cnt"] or 0)

            return {
                "period": "daily",
                "labels": days_labels,
                "datasets": {
                    "revenue": revenue_series,
                    "profit": profit_series,
                    "sales_count": count_series,
                },
            }
