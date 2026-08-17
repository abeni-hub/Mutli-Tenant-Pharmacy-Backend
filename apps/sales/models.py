from django.db import models
from django.utils import timezone

from core.models import TenantScopedModel


class Sale(TenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        HELD = "held", "Held"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially Refunded"
        REFUNDED = "refunded", "Fully Refunded"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card / POS"
        MOBILE_MONEY = "mobile_money", "Mobile Money (Telebirr/CBE)"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        SPLIT = "split", "Split Payment"
        OTHER = "other", "Other"

    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PARTIAL = "partial", "Partial"
        PAID = "paid", "Paid"
        REFUNDED = "refunded", "Refunded"
        FAILED = "failed", "Failed"

    class SaleSource(models.TextChoices):
        POS = "pos", "POS"
        MANUAL = "manual", "Manual"
        ONLINE = "online", "Online"

    receipt_number = models.CharField(max_length=100, blank=True, db_index=True)
    sale_reference = models.CharField(max_length=100, blank=True, db_index=True)
    invoice_number = models.CharField(max_length=100, db_index=True)
    customer_name = models.CharField(max_length=200, blank=True)
    customer_phone = models.CharField(max_length=50, blank=True)
    customer = models.UUIDField(null=True, blank=True)
    cashier = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="processed_sales"
    )
    pharmacist = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pharmacist_sales",
    )
    branch = models.CharField(max_length=200, blank=True)
    payment_method = models.CharField(
        max_length=30, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    payment_status = models.CharField(
        max_length=30, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.COMPLETED
    )
    sale_source = models.CharField(
        max_length=20, choices=SaleSource.choices, default=SaleSource.POS
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
    discount_breakdown = models.JSONField(default=dict, blank=True)
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text="Tax / VAT rate percentage (e.g. 15.00)",
    )
    tax_breakdown = models.JSONField(default=dict, blank=True)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    change_returned = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    loyalty_points = models.IntegerField(default=0)
    internal_remarks = models.TextField(blank=True)

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


class Prescription(TenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_REVIEW = "pending_review", "Pending Review"
        VERIFIED = "verified", "Verified"
        APPROVED = "approved", "Approved"
        PARTIALLY_DISPENSED = "partially_dispensed", "Partially Dispensed"
        FULLY_DISPENSED = "fully_dispensed", "Fully Dispensed"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"
        REJECTED = "rejected", "Rejected"

    rx_number = models.CharField(max_length=100, db_index=True)
    customer_name = models.CharField(max_length=200)
    customer_id = models.CharField(max_length=100, blank=True)
    doctor_name = models.CharField(max_length=200)
    doctor_license = models.CharField(max_length=100, blank=True)
    date = models.DateField(default=timezone.now)
    expiry_date = models.DateField(null=True, blank=True)
    branch = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING_REVIEW)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_prescriptions"
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Rx {self.rx_number} - {self.customer_name}"


class PrescriptionItem(TenantScopedModel):
    prescription = models.ForeignKey(
        Prescription, on_delete=models.CASCADE, related_name="items"
    )
    product_name = models.CharField(max_length=200)
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.SET_NULL, null=True, blank=True, related_name="prescription_items"
    )
    dosage = models.CharField(max_length=100, blank=True)
    frequency = models.CharField(max_length=100, blank=True)
    duration = models.CharField(max_length=100, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    dispensed_quantity = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"{self.product_name} ({self.prescription.rx_number})"
