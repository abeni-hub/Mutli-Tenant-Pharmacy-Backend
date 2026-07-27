from django.db import models
from django.db.models import Sum
from django.utils import timezone

from core.models import TenantScopedModel


class Product(TenantScopedModel):
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=100)
    generic_name = models.CharField(max_length=200, blank=True)
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
