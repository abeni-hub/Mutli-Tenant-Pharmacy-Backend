from rest_framework import serializers

from apps.catalog.models import Product
from apps.inventory.models import InventoryLog, StockBatch


class StockBatchSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_near_expiry = serializers.SerializerMethodField()
    is_depleted = serializers.BooleanField(read_only=True)

    class Meta:
        model = StockBatch
        fields = (
            "id",
            "product",
            "product_name",
            "product_sku",
            "batch_number",
            "quantity",
            "initial_quantity",
            "unit_price",
            "selling_price",
            "expiry_date",
            "manufacture_date",
            "supplier",
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
            "is_expired",
            "is_near_expiry",
            "is_depleted",
            "created_at",
            "updated_at",
        )

    def get_is_near_expiry(self, obj: StockBatch) -> bool:
        return obj.is_near_expiry(threshold_days=60)


class StockInSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    batch_number = serializers.CharField(max_length=100)
    quantity = serializers.IntegerField(min_value=1)
    expiry_date = serializers.DateField()
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    selling_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    manufacture_date = serializers.DateField(required=False, allow_null=True, default=None)
    supplier = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
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
