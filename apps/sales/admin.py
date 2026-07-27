from django.contrib import admin

from apps.sales.models import Sale, SaleItem, SaleRefund


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0
    readonly_fields = (
        "product",
        "batch",
        "quantity",
        "unit_cost_price",
        "unit_selling_price",
        "discount_amount",
        "total_cost",
        "total_price",
        "profit",
        "quantity_refunded",
    )


class SaleRefundInline(admin.TabularInline):
    model = SaleRefund
    extra = 0
    readonly_fields = ("refund_number", "refund_amount", "reason", "processed_by", "created_at")


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "tenant",
        "customer_name",
        "cashier",
        "payment_method",
        "status",
        "subtotal",
        "discount_amount",
        "tax_amount",
        "total_amount",
        "total_profit",
        "created_at",
    )
    list_filter = ("status", "payment_method", "is_taxable")
    search_fields = ("invoice_number", "customer_name", "customer_phone", "cashier__email")
    inlines = [SaleItemInline, SaleRefundInline]
    readonly_fields = ("created_at", "updated_at", "cancelled_at")


@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = (
        "sale",
        "product",
        "batch",
        "quantity",
        "unit_cost_price",
        "unit_selling_price",
        "total_price",
        "profit",
    )
    search_fields = ("sale__invoice_number", "product__name", "batch__batch_number")


@admin.register(SaleRefund)
class SaleRefundAdmin(admin.ModelAdmin):
    list_display = ("refund_number", "sale", "refund_amount", "processed_by", "created_at")
    search_fields = ("refund_number", "sale__invoice_number")
