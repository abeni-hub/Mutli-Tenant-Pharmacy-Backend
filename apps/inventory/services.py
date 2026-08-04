"""
Inventory service layer.

Handles Stock In, FIFO Stock Out, Stock Adjustments, Expired write-offs,
and stock status queries (Expired, Near-Expiry, Low-Stock).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import AuditService
from apps.catalog.models import Product
from apps.inventory.models import InventoryLog, StockBatch

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.tenants.models import Tenant


class InventoryService:
    @staticmethod
    @transaction.atomic
    def stock_in(
        *,
        tenant: Tenant,
        product: Product,
        batch_number: str,
        quantity: int,
        expiry_date: date,
        unit_price: Decimal | float,
        selling_price: Decimal | float,
        manufacture_date: date | None = None,
        purchase_date: date | None = None,
        supplier: str = "",
        purchase_order_reference: str = "",
        warehouse: str = "",
        branch: str = "",
        location: str = "",
        reorder_level: int = 0,
        reorder_quantity: int = 0,
        notes: str = "",
        batch_status: str = "active",
        reference_number: str = "",
        performed_by: User | None = None,
    ) -> StockBatch:
        """Receive new stock or append quantity to an existing batch."""
        if quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than zero for Stock In."})

        batch, created = StockBatch.unscoped.select_for_update().get_or_create(
            tenant=tenant,
            product=product,
            batch_number=batch_number,
            defaults={
                "quantity": quantity,
                "initial_quantity": quantity,
                "unit_price": Decimal(str(unit_price)),
                "selling_price": Decimal(str(selling_price)),
                "expiry_date": expiry_date,
                "manufacture_date": manufacture_date,
                "purchase_date": purchase_date,
                "supplier": supplier,
                "purchase_order_reference": purchase_order_reference,
                "warehouse": warehouse,
                "branch": branch,
                "location": location,
                "reorder_level": reorder_level,
                "reorder_quantity": reorder_quantity,
                "notes": notes,
                "batch_status": batch_status,
                "is_active": True,
            },
        )

        prev_qty = 0 if created else (batch.quantity - quantity)
        if not created:
            prev_qty = batch.quantity
            batch.quantity += quantity
            batch.unit_price = Decimal(str(unit_price))
            batch.selling_price = Decimal(str(selling_price))
            batch.expiry_date = expiry_date
            if manufacture_date:
                batch.manufacture_date = manufacture_date
            if purchase_date:
                batch.purchase_date = purchase_date
            if supplier:
                batch.supplier = supplier
            if purchase_order_reference:
                batch.purchase_order_reference = purchase_order_reference
            if warehouse:
                batch.warehouse = warehouse
            if branch:
                batch.branch = branch
            if location:
                batch.location = location
            if reorder_level:
                batch.reorder_level = reorder_level
            if reorder_quantity:
                batch.reorder_quantity = reorder_quantity
            if notes:
                batch.notes = notes
            if batch_status:
                batch.batch_status = batch_status
            batch.save()

        # Audit Log
        InventoryLog.unscoped.create(
            tenant=tenant,
            product=product,
            batch=batch,
            transaction_type=InventoryLog.TransactionType.STOCK_IN,
            quantity_changed=quantity,
            previous_quantity=prev_qty,
            new_quantity=batch.quantity,
            reason=f"Stock In receipt ({supplier})" if supplier else "Stock In receipt",
            reference_number=reference_number,
            performed_by=performed_by,
        )

        AuditService.record(
            tenant=tenant,
            actor=performed_by,
            action="create" if created else "update",
            entity_type="inventory.StockBatch",
            entity_id=batch.id,
            metadata={
                "batch_number": batch_number,
                "product_id": str(product.id),
                "quantity_added": quantity,
                "new_total": batch.quantity,
            },
        )
        return batch

    @staticmethod
    @transaction.atomic
    def stock_out_fifo(
        *,
        tenant: Tenant,
        product: Product,
        quantity: int,
        reason: str = "Sale Dispense",
        reference_number: str = "",
        batch_id: str | None = None,
        performed_by: User | None = None,
    ) -> list[dict[str, Any]]:
        """
        Deduct stock using FIFO algorithm (First In First Out based on earliest expiry date).

        Returns:
            List of dicts representing batch deductions made:
            [{ "batch_id": UUID, "batch_number": str, "quantity_deducted": int, "remaining_batch_qty": int }]
        """
        if quantity <= 0:
            raise ValidationError({"quantity": "Quantity to deduct must be greater than zero."})

        today = timezone.now().date()
        filters = {
            "tenant": tenant,
            "product": product,
            "is_active": True,
            "quantity__gt": 0,
            "expiry_date__gt": today,
        }
        if batch_id:
            filters["id"] = batch_id
        available_batches = (
            StockBatch.unscoped.select_for_update()
            .filter(**filters)
            .order_by("expiry_date", "created_at")
        )

        total_available = sum(b.quantity for b in available_batches)
        if total_available < quantity:
            raise ValidationError(
                {
                    "quantity": f"Insufficient stock for '{product.name}'. Available: {total_available}, Requested: {quantity}."
                }
            )

        remaining_needed = quantity
        deductions = []

        for batch in available_batches:
            if remaining_needed <= 0:
                break

            deduct_amount = min(batch.quantity, remaining_needed)
            prev_qty = batch.quantity
            new_qty = prev_qty - deduct_amount
            batch.quantity = new_qty
            batch.save(update_fields=["quantity"])

            InventoryLog.unscoped.create(
                tenant=tenant,
                product=product,
                batch=batch,
                transaction_type=InventoryLog.TransactionType.STOCK_OUT,
                quantity_changed=-deduct_amount,
                previous_quantity=prev_qty,
                new_quantity=new_qty,
                reason=reason,
                reference_number=reference_number,
                performed_by=performed_by,
            )

            deductions.append(
                {
                    "batch_id": batch.id,
                    "batch_number": batch.batch_number,
                    "quantity_deducted": deduct_amount,
                    "remaining_batch_qty": new_qty,
                    "expiry_date": batch.expiry_date,
                    "selling_price": str(batch.selling_price),
                }
            )

            remaining_needed -= deduct_amount

        AuditService.record(
            tenant=tenant,
            actor=performed_by,
            action="update",
            entity_type="catalog.Product",
            entity_id=product.id,
            metadata={
                "action": "STOCK_OUT_FIFO",
                "product": product.name,
                "total_deducted": quantity,
                "batches_affected": len(deductions),
            },
        )
        return deductions

    @staticmethod
    @transaction.atomic
    def transfer_stock(
        *,
        tenant: Tenant,
        batch: StockBatch,
        quantity: int,
        destination: str,
        reason: str = "Transfer",
        reference_number: str = "",
        performed_by: User | None = None,
    ) -> StockBatch:
        if quantity <= 0:
            raise ValidationError({"quantity": "Transfer quantity must be greater than zero."})
        if quantity > batch.available_quantity:
            raise ValidationError({"quantity": "Transfer quantity exceeds available quantity."})

        prev_qty = batch.quantity
        batch.quantity -= quantity
        batch.save(update_fields=["quantity", "updated_at"])

        InventoryLog.unscoped.create(
            tenant=tenant,
            product=batch.product,
            batch=batch,
            transaction_type=InventoryLog.TransactionType.TRANSFER,
            quantity_changed=-quantity,
            previous_quantity=prev_qty,
            new_quantity=batch.quantity,
            reason=f"{reason}: {destination}",
            reference_number=reference_number,
            performed_by=performed_by,
        )
        return batch

    @staticmethod
    @transaction.atomic
    def archive_batch(*, tenant: Tenant, batch: StockBatch, reason: str = "Archived", performed_by: User | None = None) -> StockBatch:
        batch.is_active = False
        batch.batch_status = StockBatch.BatchStatus.ARCHIVED
        batch.save(update_fields=["is_active", "batch_status", "updated_at"])
        InventoryLog.unscoped.create(
            tenant=tenant,
            product=batch.product,
            batch=batch,
            transaction_type=InventoryLog.TransactionType.ARCHIVE,
            quantity_changed=0,
            previous_quantity=batch.quantity,
            new_quantity=batch.quantity,
            reason=reason,
            performed_by=performed_by,
        )
        return batch

    @staticmethod
    @transaction.atomic
    def restore_batch(*, tenant: Tenant, batch: StockBatch, performed_by: User | None = None) -> StockBatch:
        batch.is_active = True
        batch.batch_status = StockBatch.BatchStatus.ACTIVE
        batch.save(update_fields=["is_active", "batch_status", "updated_at"])
        InventoryLog.unscoped.create(
            tenant=tenant,
            product=batch.product,
            batch=batch,
            transaction_type=InventoryLog.TransactionType.RESTORE,
            quantity_changed=0,
            previous_quantity=batch.quantity,
            new_quantity=batch.quantity,
            reason="Batch restored",
            performed_by=performed_by,
        )
        return batch

    @staticmethod
    def get_inventory_summary(tenant: Tenant) -> dict[str, Any]:
        today = timezone.now().date()
        batches = StockBatch.unscoped.filter(tenant=tenant, is_active=True).select_related("product")
        total_value = sum((batch.quantity * batch.unit_price) for batch in batches)
        low_stock = sum(1 for batch in batches if batch.available_quantity <= batch.reorder_level) if batches else 0
        near_expiry = batches.filter(expiry_date__gt=today, expiry_date__lte=today + timedelta(days=45)).count()
        expired = batches.filter(expiry_date__lte=today).count()
        return {
            "total_value": round(float(total_value), 2),
            "low_stock_batches": low_stock,
            "near_expiry_batches": near_expiry,
            "expired_batches": expired,
        }

    @staticmethod
    def get_inventory_valuation(tenant: Tenant) -> dict[str, Any]:
        batches = StockBatch.unscoped.filter(tenant=tenant, is_active=True).select_related("product")
        total_units = batches.aggregate(total_units=Sum("quantity"))["total_units"] or 0
        total_value = sum((batch.quantity * batch.unit_price) for batch in batches)
        return {"total_units": total_units, "total_value": round(float(total_value), 2)}

    @staticmethod
    def get_batch_history(tenant: Tenant, batch: StockBatch) -> list[InventoryLog]:
        return list(
            InventoryLog.unscoped.select_related("product", "performed_by")
            .filter(tenant=tenant, batch=batch)
            .order_by("-created_at")
        )

    @staticmethod
    @transaction.atomic
    def adjust_stock(
        *,
        tenant: Tenant,
        batch: StockBatch,
        new_quantity: int,
        reason: str,
        reference_number: str = "",
        performed_by: User | None = None,
    ) -> StockBatch:
        """Manually adjust quantity of a specific stock batch with audit logging."""
        if new_quantity < 0:
            raise ValidationError({"new_quantity": "Quantity cannot be negative."})

        if not reason.strip():
            raise ValidationError({"reason": "A reason is required for stock adjustments."})

        prev_qty = batch.quantity
        qty_change = new_quantity - prev_qty
        batch.quantity = new_quantity
        batch.save(update_fields=["quantity"])

        InventoryLog.unscoped.create(
            tenant=tenant,
            product=batch.product,
            batch=batch,
            transaction_type=InventoryLog.TransactionType.ADJUSTMENT,
            quantity_changed=qty_change,
            previous_quantity=prev_qty,
            new_quantity=new_quantity,
            reason=reason,
            reference_number=reference_number,
            performed_by=performed_by,
        )

        AuditService.record(
            tenant=tenant,
            actor=performed_by,
            action="update",
            entity_type="inventory.StockBatch",
            entity_id=batch.id,
            metadata={
                "action": "STOCK_ADJUSTMENT",
                "batch_number": batch.batch_number,
                "prev_qty": prev_qty,
                "new_qty": new_quantity,
                "reason": reason,
            },
        )
        return batch

    @staticmethod
    @transaction.atomic
    def transfer_stock(
        *,
        tenant: Tenant,
        batch: StockBatch,
        quantity: int,
        destination: str,
        reason: str = "Transfer",
        reference_number: str = "",
        performed_by: User | None = None,
    ) -> StockBatch:
        if quantity <= 0:
            raise ValidationError({"quantity": "Transfer quantity must be greater than zero."})
        if quantity > batch.available_quantity:
            raise ValidationError({"quantity": "Transfer quantity exceeds available quantity."})

        prev_qty = batch.quantity
        batch.quantity -= quantity
        batch.save(update_fields=["quantity", "updated_at"])

        InventoryLog.unscoped.create(
            tenant=tenant,
            product=batch.product,
            batch=batch,
            transaction_type=InventoryLog.TransactionType.TRANSFER,
            quantity_changed=-quantity,
            previous_quantity=prev_qty,
            new_quantity=batch.quantity,
            reason=f"{reason}: {destination}",
            reference_number=reference_number,
            performed_by=performed_by,
        )
        return batch

    @staticmethod
    @transaction.atomic
    def archive_batch(*, tenant: Tenant, batch: StockBatch, reason: str = "Archived", performed_by: User | None = None) -> StockBatch:
        batch.is_active = False
        batch.batch_status = StockBatch.BatchStatus.ARCHIVED
        batch.save(update_fields=["is_active", "batch_status", "updated_at"])
        InventoryLog.unscoped.create(
            tenant=tenant,
            product=batch.product,
            batch=batch,
            transaction_type=InventoryLog.TransactionType.ARCHIVE,
            quantity_changed=0,
            previous_quantity=batch.quantity,
            new_quantity=batch.quantity,
            reason=reason,
            performed_by=performed_by,
        )
        return batch

    @staticmethod
    @transaction.atomic
    def restore_batch(*, tenant: Tenant, batch: StockBatch, performed_by: User | None = None) -> StockBatch:
        batch.is_active = True
        batch.batch_status = StockBatch.BatchStatus.ACTIVE
        batch.save(update_fields=["is_active", "batch_status", "updated_at"])
        InventoryLog.unscoped.create(
            tenant=tenant,
            product=batch.product,
            batch=batch,
            transaction_type=InventoryLog.TransactionType.RESTORE,
            quantity_changed=0,
            previous_quantity=batch.quantity,
            new_quantity=batch.quantity,
            reason="Batch restored",
            performed_by=performed_by,
        )
        return batch

    @staticmethod
    def get_expired_batches(tenant: Tenant) -> list[StockBatch]:
        """Return batches with expiry_date <= today and remaining quantity > 0."""
        today = timezone.now().date()
        return list(
            StockBatch.unscoped.select_related("product")
            .filter(tenant=tenant, is_active=True, quantity__gt=0, expiry_date__lte=today)
            .order_by("expiry_date")
        )

    @staticmethod
    def get_near_expiry_batches(tenant: Tenant, threshold_days: int = 60) -> list[StockBatch]:
        """Return batches expiring within threshold_days (default 60 days) with remaining quantity > 0."""
        today = timezone.now().date()
        threshold_date = today + timedelta(days=threshold_days)
        return list(
            StockBatch.unscoped.select_related("product")
            .filter(
                tenant=tenant,
                is_active=True,
                quantity__gt=0,
                expiry_date__gt=today,
                expiry_date__lte=threshold_date,
            )
            .order_by("expiry_date")
        )

    @staticmethod
    def get_low_stock_products(tenant: Tenant) -> list[dict[str, Any]]:
        """Return products where total active, non-expired batch stock is <= reorder_level."""
        today = timezone.now().date()
        products = Product.unscoped.filter(tenant=tenant, is_active=True)
        low_stock_list = []

        for p in products:
            total_stock = (
                StockBatch.unscoped.filter(
                    tenant=tenant,
                    product=p,
                    is_active=True,
                    quantity__gt=0,
                    expiry_date__gt=today,
                ).aggregate(total=Sum("quantity"))["total"]
                or 0
            )

            if total_stock <= p.reorder_level:
                low_stock_list.append(
                    {
                        "product_id": p.id,
                        "product_name": p.name,
                        "sku": p.sku,
                        "current_stock": total_stock,
                        "reorder_level": p.reorder_level,
                    }
                )

        return low_stock_list
