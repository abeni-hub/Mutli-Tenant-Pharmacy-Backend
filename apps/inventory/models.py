from datetime import timedelta

from django.db import models
from django.utils import timezone

from core.models import TenantScopedModel


class StockBatch(TenantScopedModel):
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="batches"
    )
    batch_number = models.CharField(max_length=100)
    quantity = models.IntegerField(default=0, help_text="Current available balance")
    initial_quantity = models.IntegerField(default=0, help_text="Initial quantity when received")
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00, help_text="Purchase/cost price"
    )
    selling_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00, help_text="Retail selling price"
    )
    expiry_date = models.DateField(help_text="Expiration date")
    manufacture_date = models.DateField(null=True, blank=True)
    supplier = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("expiry_date", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "product", "batch_number"),
                name="unique_batch_per_product_tenant",
            )
        ]

    def __str__(self) -> str:
        return f"Batch {self.batch_number} - {self.product.name} (Qty: {self.quantity})"

    @property
    def is_expired(self) -> bool:
        return timezone.now().date() >= self.expiry_date

    def is_near_expiry(self, threshold_days: int = 60) -> bool:
        today = timezone.now().date()
        return today < self.expiry_date <= (today + timedelta(days=threshold_days))

    @property
    def is_depleted(self) -> bool:
        return self.quantity <= 0


class InventoryLog(TenantScopedModel):
    class TransactionType(models.TextChoices):
        STOCK_IN = "stock_in", "Stock In"
        STOCK_OUT = "stock_out", "Stock Out (FIFO)"
        ADJUSTMENT = "adjustment", "Stock Adjustment"
        EXPIRED_DISCARD = "expired_discard", "Expired Discard"
        RETURN = "return", "Customer Return"

    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="inventory_logs"
    )
    batch = models.ForeignKey(
        StockBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs",
    )
    transaction_type = models.CharField(max_length=30, choices=TransactionType.choices)
    quantity_changed = models.IntegerField(help_text="Positive for addition, negative for deduction")
    previous_quantity = models.IntegerField()
    new_quantity = models.IntegerField()
    reason = models.TextField(blank=True)
    reference_number = models.CharField(max_length=100, blank=True)
    performed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_logs",
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"InventoryLog({self.transaction_type}, {self.product.name}, {self.quantity_changed})"
