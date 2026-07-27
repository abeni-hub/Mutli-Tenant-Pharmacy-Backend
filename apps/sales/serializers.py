from rest_framework import serializers

from apps.catalog.models import Product
from apps.sales.models import Sale, SaleItem, SaleRefund


class SaleItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True)
    expiry_date = serializers.DateField(source="batch.expiry_date", read_only=True)

    class Meta:
        model = SaleItem
        fields = (
            "id",
            "product",
            "product_name",
            "product_sku",
            "batch",
            "batch_number",
            "expiry_date",
            "quantity",
            "unit_cost_price",
            "unit_selling_price",
            "discount_amount",
            "total_cost",
            "total_price",
            "profit",
            "quantity_refunded",
        )
        read_only_fields = fields


class SaleRefundSerializer(serializers.ModelSerializer):
    processed_by_email = serializers.EmailField(
        source="processed_by.email", read_only=True, default=None
    )

    class Meta:
        model = SaleRefund
        fields = (
            "id",
            "refund_number",
            "refund_amount",
            "reason",
            "processed_by_email",
            "created_at",
        )
        read_only_fields = fields


class SaleCreateItemSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    discount_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, default=0.00, min_value=0
    )
    discount_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=0.00, min_value=0
    )

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


class SaleCreateSerializer(serializers.Serializer):
    items = SaleCreateItemSerializer(many=True, required=True)
    customer_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    customer_phone = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    payment_method = serializers.ChoiceField(
        choices=Sale.PaymentMethod.choices, default=Sale.PaymentMethod.CASH
    )
    discount_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0.00, min_value=0
    )
    discount_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=0.00, min_value=0
    )
    tax_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        default=0.00,
        min_value=0,
        help_text="Set to 0.00 for tax-free sale, or e.g. 15.00 for 15% VAT",
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required for checkout.")
        return value


class SaleListSerializer(serializers.ModelSerializer):
    cashier_name = serializers.SerializerMethodField()
    items_count = serializers.IntegerField(source="items.count", read_only=True)

    class Meta:
        model = Sale
        fields = (
            "id",
            "invoice_number",
            "customer_name",
            "customer_phone",
            "cashier_name",
            "payment_method",
            "status",
            "is_taxable",
            "subtotal",
            "discount_amount",
            "tax_rate",
            "tax_amount",
            "total_amount",
            "total_profit",
            "items_count",
            "created_at",
        )
        read_only_fields = fields

    def get_cashier_name(self, obj: Sale) -> str:
        if obj.cashier:
            return f"{obj.cashier.first_name} {obj.cashier.last_name}".strip() or obj.cashier.email
        return "Unknown"


class SaleDetailSerializer(serializers.ModelSerializer):
    items = SaleItemSerializer(many=True, read_only=True)
    refunds = SaleRefundSerializer(many=True, read_only=True)
    cashier_name = serializers.SerializerMethodField()
    cancelled_by_email = serializers.EmailField(
        source="cancelled_by.email", read_only=True, default=None
    )
    receipt = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = (
            "id",
            "invoice_number",
            "customer_name",
            "customer_phone",
            "cashier_name",
            "payment_method",
            "status",
            "is_taxable",
            "subtotal",
            "discount_amount",
            "tax_rate",
            "tax_amount",
            "total_amount",
            "total_cost",
            "total_profit",
            "notes",
            "cancelled_at",
            "cancelled_by_email",
            "cancellation_reason",
            "created_at",
            "items",
            "refunds",
            "receipt",
        )
        read_only_fields = fields

    def get_cashier_name(self, obj: Sale) -> str:
        if obj.cashier:
            return f"{obj.cashier.first_name} {obj.cashier.last_name}".strip() or obj.cashier.email
        return "Unknown"

    def get_receipt(self, obj: Sale) -> dict:
        """Structured receipt format for printing or PDF rendering."""
        return {
            "pharmacy_name": obj.tenant.name if hasattr(obj, "tenant") else "Pharmacy",
            "invoice_number": obj.invoice_number,
            "date": obj.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "cashier": self.get_cashier_name(obj),
            "customer": obj.customer_name or "Walk-in Customer",
            "payment_method": obj.get_payment_method_display(),
            "items": [
                {
                    "item_name": item.product.name,
                    "batch_number": item.batch.batch_number,
                    "quantity": item.quantity,
                    "unit_price": str(item.unit_selling_price),
                    "discount": str(item.discount_amount),
                    "total_price": str(item.total_price),
                }
                for item in obj.items.all()
            ],
            "subtotal": str(obj.subtotal),
            "discount_total": str(obj.discount_amount),
            "tax_rate": f"{obj.tax_rate}%" if obj.is_taxable else "0% (Tax-Free)",
            "tax_total": str(obj.tax_amount),
            "grand_total": str(obj.total_amount),
            "status": obj.get_status_display(),
        }


class SaleCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, min_length=3)


class SaleRefundInputSerializer(serializers.Serializer):
    item_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(required=True, min_length=3)
