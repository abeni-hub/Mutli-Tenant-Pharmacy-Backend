from datetime import date

from rest_framework import serializers

from apps.catalog.models import Product
from apps.inventory.models import InventoryLog, StockBatch


class StockBatchSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_near_expiry = serializers.SerializerMethodField()
    is_depleted = serializers.BooleanField(read_only=True)

    available_quantity = serializers.IntegerField(read_only=True)
    stock_status = serializers.CharField(read_only=True)

    class Meta:
        model = StockBatch
        fields = (
            "id",
            "product",
            "product_name",
            "product_sku",
            "batch_number",
            "lot_number",
            "purchase_date",
            "quantity",
            "initial_quantity",
            "reserved_quantity",
            "available_quantity",
            "unit_price",
            "selling_price",
            "expiry_date",
            "manufacture_date",
            "supplier",
            "purchase_order_reference",
            "warehouse",
            "branch",
            "location",
            "reorder_level",
            "reorder_quantity",
            "stock_status",
            "batch_status",
            "notes",
            "is_active",
            "is_expired",
            "is_near_expiry",
            "is_depleted",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "product_name",
            "product_sku",
            "initial_quantity",
            "available_quantity",
            "stock_status",
            "is_expired",
            "is_near_expiry",
            "is_depleted",
            "created_at",
            "updated_at",
        )

    def get_is_near_expiry(self, obj: StockBatch) -> bool:
        return obj.is_near_expiry(threshold_days=60)

    def validate(self, attrs):
        expiry_date = attrs.get("expiry_date")
        manufacture_date = attrs.get("manufacture_date")
        purchase_date = attrs.get("purchase_date")
        quantity = attrs.get("quantity")
        reserved_quantity = attrs.get("reserved_quantity")

        if expiry_date and manufacture_date and manufacture_date > expiry_date:
            raise serializers.ValidationError({"manufacture_date": "Manufacture date cannot be after expiry date."})
        if purchase_date and expiry_date and purchase_date > expiry_date:
            raise serializers.ValidationError({"purchase_date": "Purchase date cannot be after expiry date."})
        if quantity is not None and quantity < 0:
            raise serializers.ValidationError({"quantity": "Quantity cannot be negative."})
        if reserved_quantity is not None and reserved_quantity < 0:
            raise serializers.ValidationError({"reserved_quantity": "Reserved quantity cannot be negative."})
        if quantity is not None and reserved_quantity is not None and reserved_quantity > quantity:
            raise serializers.ValidationError({"reserved_quantity": "Reserved quantity cannot exceed total quantity."})

        return attrs


class StockInSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    batch_number = serializers.CharField(max_length=100)
    lot_number = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    quantity = serializers.IntegerField(min_value=1)
    expiry_date = serializers.DateField()
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    selling_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    manufacture_date = serializers.DateField(required=False, allow_null=True, default=None)
    purchase_date = serializers.DateField(required=False, allow_null=True, default=None)
    supplier = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    purchase_order_reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    warehouse = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    branch = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    location = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    reorder_level = serializers.IntegerField(required=False, min_value=0, default=0)
    reorder_quantity = serializers.IntegerField(required=False, min_value=0, default=0)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    batch_status = serializers.CharField(required=False, allow_blank=True, default="active")
    reference_number = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")

    def validate_product_id(self, value):
        request = self.context.get("request")
        tenant_id = getattr(request, "tenant_id", None) if request else None
        try:
            if tenant_id:
                product = Product.objects.get(id=value, tenant_id=tenant_id)
            else:
                product = Product.objects.get(id=value)
        except Product.DoesNotExist:
            raise serializers.ValidationError("Product not found or access denied.")
        return product


class StockOutFIFOSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(required=False, allow_blank=True, default="Sale Dispense")
    reference_number = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    batch_id = serializers.UUIDField(required=False, allow_null=True, default=None)

    def validate_product_id(self, value):
        request = self.context.get("request")
        tenant_id = getattr(request, "tenant_id", None) if request else None
        try:
            if tenant_id:
                product = Product.objects.get(id=value, tenant_id=tenant_id)
            else:
                product = Product.objects.get(id=value)
        except Product.DoesNotExist:
            raise serializers.ValidationError("Product not found or access denied.")
        return product


class StockAdjustmentSerializer(serializers.Serializer):
    batch_id = serializers.UUIDField()
    new_quantity = serializers.IntegerField(min_value=0)
    reason = serializers.CharField(required=True, min_length=3)
    reference_number = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        batch = attrs.get("batch_id")
        new_quantity = attrs.get("new_quantity")
        if batch and new_quantity is not None and new_quantity < 0:
            raise serializers.ValidationError({"new_quantity": "Quantity cannot be negative."})
        return attrs

    def validate_batch_id(self, value):
        request = self.context.get("request")
        tenant_id = getattr(request, "tenant_id", None) if request else None
        try:
            if tenant_id:
                batch = StockBatch.objects.get(id=value, tenant_id=tenant_id)
            else:
                batch = StockBatch.objects.get(id=value)
        except StockBatch.DoesNotExist:
            raise serializers.ValidationError("Stock batch not found or access denied.")
        return batch


class TransferSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)
    destination = serializers.CharField(required=True, min_length=2)
    reason = serializers.CharField(required=False, allow_blank=True, default="Transfer")
    reference_number = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class InventoryLogSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True, default=None)
    performed_by_email = serializers.EmailField(source="performed_by.email", read_only=True, default=None)

    class Meta:
        model = InventoryLog
        fields = (
            "id",
            "product",
            "product_name",
            "product_sku",
            "batch",
            "batch_number",
            "transaction_type",
            "quantity_changed",
            "previous_quantity",
            "new_quantity",
            "reason",
            "reference_number",
            "performed_by_email",
            "created_at",
        )
        read_only_fields = fields


class LowStockProductSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    product_name = serializers.CharField()
    sku = serializers.CharField()
    current_stock = serializers.IntegerField()
    reorder_level = serializers.IntegerField()
