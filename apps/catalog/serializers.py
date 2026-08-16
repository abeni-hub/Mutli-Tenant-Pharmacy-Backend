from decimal import Decimal

from rest_framework import serializers

from apps.catalog.models import Product


class ProductSerializer(serializers.ModelSerializer):
    purchase_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.00"), required=False, allow_null=True)
    selling_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.00"), required=False, allow_null=True)
    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0.00"), required=False, allow_null=True)
    available_stock = serializers.IntegerField(required=False, min_value=0)
    min_stock = serializers.IntegerField(required=False, min_value=0)
    max_stock = serializers.IntegerField(required=False, min_value=0)
    reorder_level = serializers.IntegerField(required=False, min_value=0)

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "sku",
            "generic_name",
            "brand_name",
            "barcode",
            "category",
            "manufacturer",
            "supplier_id",
            "purchase_price",
            "selling_price",
            "tax_rate",
            "available_stock",
            "min_stock",
            "max_stock",
            "unit",
            "strength",
            "dosage_form",
            "batch_number",
            "expiry_date",
            "description",
            "status",
            "requires_prescription",
            "controlled_drug",
            "refrigerated",
            "image_url",
            "reorder_level",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs):
        selling_price = attrs.get("selling_price")
        purchase_price = attrs.get("purchase_price")
        if selling_price is not None and purchase_price is not None:
            if selling_price < purchase_price:
                raise serializers.ValidationError({"selling_price": "Selling price must be greater than or equal to cost price."})

        min_stock = attrs.get("min_stock")
        max_stock = attrs.get("max_stock")
        if min_stock is not None and max_stock is not None and max_stock < min_stock:
            raise serializers.ValidationError({"max_stock": "Maximum stock must be greater than or equal to minimum stock."})

        return attrs

    def create(self, validated_data):
        tenant_id = self.context.get("tenant_id") or validated_data.get("tenant_id")
        if tenant_id:
            validated_data["tenant_id"] = tenant_id
        if "status" in validated_data and "is_active" not in validated_data:
            validated_data["is_active"] = validated_data["status"] != "inactive"
        elif "is_active" in validated_data and "status" not in validated_data:
            validated_data["status"] = "active" if validated_data["is_active"] else "inactive"
        return Product.objects.create(**validated_data)

    def update(self, instance, validated_data):
        if "status" in validated_data and "is_active" not in validated_data:
            validated_data["is_active"] = validated_data["status"] != "inactive"
        elif "is_active" in validated_data and "status" not in validated_data:
            validated_data["status"] = "active" if validated_data["is_active"] else "inactive"

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

    def validate_sku(self, value):
        tenant_id = self.context.get("tenant_id")
        if not tenant_id:
            return value
        qs = Product.objects.filter(tenant_id=tenant_id, sku__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A product with this SKU already exists for this tenant.")
        return value

    def validate_barcode(self, value):
        tenant_id = self.context.get("tenant_id")
        if not tenant_id or not value:
            return value
        qs = Product.objects.filter(tenant_id=tenant_id, barcode=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A product with this barcode already exists for this tenant.")
        return value
