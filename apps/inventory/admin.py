from django.contrib import admin

from apps.inventory.models import InventoryLog, StockBatch


@admin.register(StockBatch)
class StockBatchAdmin(admin.ModelAdmin):
    list_display = (
        "batch_number",
        "product",
        "tenant",
        "quantity",
        "initial_quantity",
        "unit_price",
        "selling_price",
        "expiry_date",
        "is_active",
    )
    list_filter = ("is_active", "expiry_date")
    search_fields = ("batch_number", "product__name", "product__sku", "supplier")
    ordering = ("expiry_date",)


@admin.register(InventoryLog)
class InventoryLogAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_type",
        "product",
        "batch",
        "tenant",
        "quantity_changed",
        "previous_quantity",
        "new_quantity",
        "reference_number",
        "performed_by",
        "created_at",
    )
    list_filter = ("transaction_type",)
    search_fields = ("reference_number", "reason", "product__name", "batch__batch_number")
    ordering = ("-created_at",)
    readonly_fields = (
        "product",
        "batch",
        "tenant",
        "transaction_type",
        "quantity_changed",
        "previous_quantity",
        "new_quantity",
        "reason",
        "reference_number",
        "performed_by",
        "created_at",
    )
