from decimal import Decimal

from rest_framework import serializers

from apps.catalog.models import Product
from apps.purchases.models import GoodsReceipt, PurchaseOrder, PurchaseOrderItem, Supplier


class SupplierSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="company_name", required=False)

    class Meta:
        model = Supplier
        fields = (
            "id",
            "code",
            "name",
            "company_name",
            "contact_person",
            "email",
            "phone",
            "address",
            "country",
            "tax_number",
            "license_number",
            "payment_terms",
            "status",
            "preferred_supplier",
            "notes",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = PurchaseOrderItem
        fields = (
            "id",
            "product",
            "product_name",
            "product_sku",
            "ordered_quantity",
            "received_quantity",
            "unit_cost",
            "discount",
            "tax",
            "total",
        )
        read_only_fields = ("id", "product_name", "product_sku", "total")


class PurchaseOrderItemInputSerializer(serializers.Serializer):
    product = serializers.UUIDField()
    ordered_quantity = serializers.IntegerField(min_value=1)
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.00"))
    discount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.00"), required=False, default=Decimal("0.00"))
    tax = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.00"), required=False, default=Decimal("0.00"))

    def validate_product(self, value):
        request = self.context.get("request")
        tenant_id = getattr(request, "tenant_id", None) if request else None
        try:
            if tenant_id:
                return Product.objects.get(id=value, tenant_id=tenant_id)
            return Product.objects.get(id=value)
        except Product.DoesNotExist as exc:
            raise serializers.ValidationError("Product not found or access denied.") from exc


class PurchaseOrderSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.company_name", read_only=True)
    item_count = serializers.IntegerField(source="items.count", read_only=True)
    items = PurchaseOrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = (
            "id",
            "po_number",
            "supplier",
            "supplier_name",
            "branch",
            "warehouse",
            "expected_delivery",
            "notes",
            "status",
            "total",
            "tax",
            "discount",
            "item_count",
            "items",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "supplier_name", "item_count", "items", "total", "tax", "discount", "created_at", "updated_at")


class PurchaseOrderCreateSerializer(serializers.Serializer):
    po_number = serializers.CharField(max_length=100)
    supplier = serializers.UUIDField()
    branch = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    warehouse = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    expected_delivery = serializers.DateField(required=False, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    status = serializers.ChoiceField(choices=PurchaseOrder.Status.choices, required=False, default=PurchaseOrder.Status.DRAFT)
    discount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=Decimal("0.00"), min_value=Decimal("0.00"))
    tax = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=Decimal("0.00"), min_value=Decimal("0.00"))
    items = PurchaseOrderItemInputSerializer(many=True, required=True)

    def validate_supplier(self, value):
        request = self.context.get("request")
        tenant_id = getattr(request, "tenant_id", None) if request else None
        try:
            if tenant_id:
                return Supplier.objects.get(id=value, tenant_id=tenant_id)
            return Supplier.objects.get(id=value)
        except Supplier.DoesNotExist as exc:
            raise serializers.ValidationError("Supplier not found or access denied.") from exc

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one purchase order item is required.")
        return value


class PurchaseReceiveSerializer(serializers.Serializer):
    complete = serializers.BooleanField(required=False, default=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class GoodsReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoodsReceipt
        fields = ("id", "purchase_order", "receipt_number", "received_at", "notes", "complete", "batch")
        read_only_fields = fields
