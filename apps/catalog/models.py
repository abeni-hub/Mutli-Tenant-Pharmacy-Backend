from django.db import models

from core.models import TenantScopedModel


class Product(TenantScopedModel):
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=100)
    generic_name = models.CharField(max_length=200, blank=True)
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
