from decimal import Decimal

from django.db import models
from django.db.models import Sum
from django.utils import timezone

from core.models import TenantScopedModel


class Product(TenantScopedModel):
    STATUS_CHOICES = (
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("draft", "Draft"),
    )

    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=100)
    generic_name = models.CharField(max_length=200, blank=True)
    brand_name = models.CharField(max_length=200, blank=True)
    barcode = models.CharField(max_length=100, blank=True)
    category = models.CharField(max_length=200, blank=True)
    manufacturer = models.CharField(max_length=200, blank=True)
    supplier_id = models.UUIDField(null=True, blank=True)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    available_stock = models.PositiveIntegerField(default=0)
    min_stock = models.PositiveIntegerField(default=0)
    max_stock = models.PositiveIntegerField(default=0)
    unit = models.CharField(max_length=50, default="pack")
    strength = models.CharField(max_length=100, blank=True)
    dosage_form = models.CharField(max_length=100, default="tablet")
    batch_number = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    requires_prescription = models.BooleanField(default=False)
    controlled_drug = models.BooleanField(default=False)
    refrigerated = models.BooleanField(default=False)
    image_url = models.URLField(blank=True)
    reorder_level = models.PositiveIntegerField(
        default=10, help_text="Minimum stock threshold for low-stock alerts"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "sku"), name="unique_product_sku_per_tenant"
            )
        ]
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.sku})"

    @property
    def total_stock(self) -> int:
        """Returns total quantity across all active, non-expired batches for this product."""
        today = timezone.now().date()
        result = self.batches.filter(
            is_active=True,
            quantity__gt=0,
            expiry_date__gt=today,
        ).aggregate(total=Sum("quantity"))["total"]
        return result or 0

    @property
    def is_low_stock(self) -> bool:
        return self.total_stock <= self.reorder_level
