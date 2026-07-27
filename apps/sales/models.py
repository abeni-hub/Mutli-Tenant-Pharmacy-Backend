from django.db import models

from core.models import TenantScopedModel


class Sale(TenantScopedModel):
    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially Refunded"
        REFUNDED = "refunded", "Fully Refunded"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card / POS"
        MOBILE_MONEY = "mobile_money", "Mobile Money (Telebirr/CBE)"
        OTHER = "other", "Other"

    invoice_number = models.CharField(max_length=100, db_index=True)
    customer_name = models.CharField(max_length=200, blank=True)
    customer_phone = models.CharField(max_length=50, blank=True)
    cashier = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="processed_sales"
    )
    payment_method = models.CharField(
        max_length=30, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.COMPLETED
    )

    is_taxable = models.BooleanField(default=False)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    discount_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0.00, help_text="Global sale discount"
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text="Tax / VAT rate percentage (e.g. 15.00)",
    )
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    # Cost of Goods Sold & Profit
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_profit = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    notes = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_sales",
    )
    cancellation_reason = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "invoice_number"),
                name="unique_invoice_per_tenant",
            )
        ]

    def __str__(self) -> str:
        return f"Invoice {self.invoice_number} - {self.total_amount} ({self.status})"


class SaleItem(TenantScopedModel):
    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="sale_items"
    )
    batch = models.ForeignKey(
        "inventory.StockBatch", on_delete=models.PROTECT, related_name="sale_items"
    )
    quantity = models.PositiveIntegerField()
    unit_cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit_selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00, help_text="Item level discount"
    )
    total_cost = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    profit = models.DecimalField(max_digits=10, decimal_places=2)
    quantity_refunded = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"{self.product.name} x{self.quantity} ({self.sale.invoice_number})"


class SaleRefund(TenantScopedModel):
    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name="refunds"
    )
    refund_number = models.CharField(max_length=100)
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField()
    processed_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="processed_refunds"
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Refund {self.refund_number} for {self.sale.invoice_number} ({self.refund_amount})"
