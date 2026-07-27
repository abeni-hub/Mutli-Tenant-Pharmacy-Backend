"""
Sales service layer.

Handles multi-item checkout with optional Tax/VAT and optional discounts,
FIFO cost price resolution, profit calculation, invoice numbering,
sale cancellation (with stock restoration), item refunds, and financial sales reporting.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit.services import AuditService
from apps.catalog.models import Product
from apps.inventory.models import StockBatch
from apps.inventory.services import InventoryService
from apps.sales.models import Sale, SaleItem, SaleRefund

if TYPE_CHECKING:
    from apps.tenants.models import Tenant


class SaleService:
    @staticmethod
    def generate_invoice_number(tenant: Tenant) -> str:
        """Generate structured unique invoice number: INV-YYYYMMDD-XXXX."""
        today_str = timezone.now().strftime("%Y%m%d")
        prefix = f"INV-{today_str}-"
        count = Sale.unscoped.filter(
            tenant=tenant, invoice_number__startswith=prefix
        ).count()
        return f"{prefix}{(count + 1):04d}"

    @staticmethod
    @transaction.atomic
    def create_sale(
        *,
        tenant: Tenant,
        cashier: User,
        items_data: list[dict[str, Any]],
        customer_name: str = "",
        customer_phone: str = "",
        payment_method: str = Sale.PaymentMethod.CASH,
        discount_amount: Decimal | float = 0.0,
        discount_percent: Decimal | float = 0.0,
        tax_rate: Decimal | float = 0.0,
        notes: str = "",
    ) -> Sale:
        """
        Process checkout for multiple medicines under a single invoice.

        Calculates FIFO batch cost, optional line-item & global discounts,
        optional Tax/VAT, total amount, and net profit.
        """
        if not items_data:
            raise ValidationError({"items": "At least one product item is required to process a sale."})

        invoice_number = SaleService.generate_invoice_number(tenant)
        tax_rate_dec = Decimal(str(tax_rate))
        global_discount_dec = Decimal(str(discount_amount))
        discount_pct_dec = Decimal(str(discount_percent))

        subtotal_dec = Decimal("0.00")
        total_cost_dec = Decimal("0.00")
        total_item_discounts_dec = Decimal("0.00")

        sale_items_to_create = []

        for item_entry in items_data:
            product_id = item_entry.get("product_id")
            quantity = item_entry.get("quantity", 0)
            item_disc_amount = Decimal(str(item_entry.get("discount_amount", 0.0)))
            item_disc_pct = Decimal(str(item_entry.get("discount_percent", 0.0)))

            if quantity <= 0:
                raise ValidationError({"items": "Item quantity must be greater than zero."})

            try:
                product = Product.unscoped.get(id=product_id, tenant=tenant)
            except Product.DoesNotExist:
                raise ValidationError({"items": f"Product with ID '{product_id}' not found."})

            # Execute FIFO stock deduction for this product
            deductions = InventoryService.stock_out_fifo(
                tenant=tenant,
                product=product,
                quantity=quantity,
                reason=f"Sale Checkout ({invoice_number})",
                reference_number=invoice_number,
                performed_by=cashier,
            )

            # Process each batch deduction
            for ded in deductions:
                batch_id = ded["batch_id"]
                ded_qty = ded["quantity_deducted"]

                try:
                    batch = StockBatch.unscoped.get(id=batch_id, tenant=tenant)
                except StockBatch.DoesNotExist:
                    raise ValidationError({"items": f"Batch '{batch_id}' not found."})

                unit_cost = batch.unit_price
                unit_sell = batch.selling_price

                # Calculate item discount for this deduction chunk
                if item_disc_pct > 0:
                    calculated_item_disc = (Decimal(ded_qty) * unit_sell * item_disc_pct) / Decimal("100.00")
                else:
                    calculated_item_disc = item_disc_amount

                line_gross = Decimal(ded_qty) * unit_sell
                line_cost = Decimal(ded_qty) * unit_cost
                line_net = max(Decimal("0.00"), line_gross - calculated_item_disc)
                line_profit = line_net - line_cost

                subtotal_dec += line_gross
                total_cost_dec += line_cost
                total_item_discounts_dec += calculated_item_disc

                sale_items_to_create.append(
                    {
                        "product": product,
                        "batch": batch,
                        "quantity": ded_qty,
                        "unit_cost_price": unit_cost,
                        "unit_selling_price": unit_sell,
                        "discount_amount": calculated_item_disc,
                        "total_cost": line_cost,
                        "total_price": line_net,
                        "profit": line_profit,
                    }
                )

        # Handle global sale discount
        if discount_pct_dec > 0:
            computed_global_discount = (subtotal_dec * discount_pct_dec) / Decimal("100.00")
        else:
            computed_global_discount = global_discount_dec

        total_discount = total_item_discounts_dec + computed_global_discount
        taxable_amount = max(Decimal("0.00"), subtotal_dec - total_discount)

        # Optional Tax / VAT calculation
        is_taxable = tax_rate_dec > 0
        if is_taxable:
            tax_amount_dec = (taxable_amount * tax_rate_dec) / Decimal("100.00")
        else:
            tax_amount_dec = Decimal("0.00")

        total_amount_dec = taxable_amount + tax_amount_dec
        total_profit_dec = (total_amount_dec - tax_amount_dec) - total_cost_dec

        # Save Sale
        sale = Sale.unscoped.create(
            tenant=tenant,
            invoice_number=invoice_number,
            customer_name=customer_name,
            customer_phone=customer_phone,
            cashier=cashier,
            payment_method=payment_method,
            status=Sale.Status.COMPLETED,
            is_taxable=is_taxable,
            subtotal=subtotal_dec,
            discount_amount=total_discount,
            tax_rate=tax_rate_dec,
            tax_amount=tax_amount_dec,
            total_amount=total_amount_dec,
            total_cost=total_cost_dec,
            total_profit=total_profit_dec,
            notes=notes,
        )

        # Save SaleItems
        for item_dict in sale_items_to_create:
            SaleItem.unscoped.create(
                tenant=tenant,
                sale=sale,
                product=item_dict["product"],
                batch=item_dict["batch"],
                quantity=item_dict["quantity"],
                unit_cost_price=item_dict["unit_cost_price"],
                unit_selling_price=item_dict["unit_selling_price"],
                discount_amount=item_dict["discount_amount"],
                total_cost=item_dict["total_cost"],
                total_price=item_dict["total_price"],
                profit=item_dict["profit"],
            )

        AuditService.record(
            tenant=tenant,
            actor=cashier,
            action="create",
            entity_type="sales.Sale",
            entity_id=sale.id,
            metadata={
                "invoice_number": invoice_number,
                "total_amount": str(total_amount_dec),
                "total_profit": str(total_profit_dec),
                "items_count": len(sale_items_to_create),
            },
        )
        return sale

    @staticmethod
    @transaction.atomic
    def cancel_sale(
        *,
        sale_id: UUID,
        cancelled_by: User,
        reason: str,
    ) -> Sale:
        """Cancel an entire sale invoice and restore stock to original batches."""
        if not reason.strip():
            raise ValidationError({"reason": "A cancellation reason is required."})

        try:
            sale = Sale.unscoped.select_for_update().get(id=sale_id)
        except Sale.DoesNotExist:
            raise ValidationError("Sale invoice not found.")

        if sale.status == Sale.Status.CANCELLED:
            raise ValidationError("Sale is already cancelled.")

        # Revert stock for each SaleItem
        items = SaleItem.unscoped.filter(sale=sale)
        for item in items:
            remaining_qty = item.quantity - item.quantity_refunded
            if remaining_qty > 0:
                InventoryService.stock_in(
                    tenant=sale.tenant,
                    product=item.product,
                    batch_number=item.batch.batch_number,
                    quantity=remaining_qty,
                    expiry_date=item.batch.expiry_date,
                    unit_price=item.unit_cost_price,
                    selling_price=item.unit_selling_price,
                    supplier="Sale Cancellation Return",
                    reference_number=f"CANCEL-{sale.invoice_number}",
                    performed_by=cancelled_by,
                )

        sale.status = Sale.Status.CANCELLED
        sale.cancelled_at = timezone.now()
        sale.cancelled_by = cancelled_by
        sale.cancellation_reason = reason
        sale.save()

        AuditService.record(
            tenant=sale.tenant,
            actor=cancelled_by,
            action="update",
            entity_type="sales.Sale",
            entity_id=sale.id,
            metadata={"status": "CANCELLED", "reason": reason},
        )
        return sale

    @staticmethod
    @transaction.atomic
    def refund_sale_item(
        *,
        sale_id: UUID,
        item_id: UUID,
        quantity_to_refund: int,
        reason: str,
        processed_by: User,
    ) -> SaleRefund:
        """Process partial or full refund for a specific line item and return stock."""
        if quantity_to_refund <= 0:
            raise ValidationError({"quantity": "Refund quantity must be greater than zero."})

        if not reason.strip():
            raise ValidationError({"reason": "A refund reason is required."})

        try:
            sale = Sale.unscoped.select_for_update().get(id=sale_id)
        except Sale.DoesNotExist:
            raise ValidationError("Sale invoice not found.")

        if sale.status == Sale.Status.CANCELLED:
            raise ValidationError("Cannot refund items from a cancelled sale.")

        try:
            item = SaleItem.unscoped.select_for_update().get(id=item_id, sale=sale)
        except SaleItem.DoesNotExist:
            raise ValidationError("Sale line item not found.")

        available_for_refund = item.quantity - item.quantity_refunded
        if quantity_to_refund > available_for_refund:
            raise ValidationError(
                {
                    "quantity": f"Cannot refund {quantity_to_refund} units. Maximum refundable quantity: {available_for_refund}."
                }
            )

        unit_refund_price = item.total_price / Decimal(str(item.quantity))
        refund_amount = round(unit_refund_price * Decimal(str(quantity_to_refund)), 2)

        # Restore refunded quantity to inventory batch
        InventoryService.stock_in(
            tenant=sale.tenant,
            product=item.product,
            batch_number=item.batch.batch_number,
            quantity=quantity_to_refund,
            expiry_date=item.batch.expiry_date,
            unit_price=item.unit_cost_price,
            selling_price=item.unit_selling_price,
            supplier="Customer Item Return Refund",
            reference_number=f"REFUND-{sale.invoice_number}",
            performed_by=processed_by,
        )

        item.quantity_refunded += quantity_to_refund
        item.save(update_fields=["quantity_refunded"])

        # Create SaleRefund record
        refund_number = f"REF-{sale.invoice_number}-{timezone.now().strftime('%M%S')}"
        refund = SaleRefund.unscoped.create(
            tenant=sale.tenant,
            sale=sale,
            refund_number=refund_number,
            refund_amount=refund_amount,
            reason=reason,
            processed_by=processed_by,
        )

        # Check if all items fully refunded
        all_items = SaleItem.unscoped.filter(sale=sale)
        all_fully_refunded = all(i.quantity_refunded >= i.quantity for i in all_items)
        sale.status = (
            Sale.Status.REFUNDED if all_fully_refunded else Sale.Status.PARTIALLY_REFUNDED
        )
        sale.save(update_fields=["status"])

        AuditService.record(
            tenant=sale.tenant,
            actor=processed_by,
            action="create",
            entity_type="sales.SaleRefund",
            entity_id=refund.id,
            metadata={
                "refund_number": refund_number,
                "amount": str(refund_amount),
                "item_id": str(item_id),
                "quantity_refunded": quantity_to_refund,
            },
        )
        return refund

    @staticmethod
    def generate_sales_report(
        *,
        tenant: Tenant,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> dict[str, Any]:
        """Generate analytics report: revenue, profit, COGS, tax, discounts, and payment methods."""
        qs = Sale.unscoped.filter(
            tenant=tenant,
            status__in=[
                Sale.Status.COMPLETED,
                Sale.Status.PARTIALLY_REFUNDED,
                Sale.Status.REFUNDED,
            ],
        )

        if start_date:
            qs = qs.filter(created_at__date__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__date__lte=end_date)

        aggregates = qs.aggregate(
            total_revenue=Sum("total_amount"),
            total_cost=Sum("total_cost"),
            total_profit=Sum("total_profit"),
            total_tax=Sum("tax_amount"),
            total_discount=Sum("discount_amount"),
            sales_count=Count("id"),
        )

        # Payment methods breakdown
        payment_breakdown = {
            "cash": qs.filter(payment_method=Sale.PaymentMethod.CASH).aggregate(Sum("total_amount"))["total_amount__sum"] or 0,
            "card": qs.filter(payment_method=Sale.PaymentMethod.CARD).aggregate(Sum("total_amount"))["total_amount__sum"] or 0,
            "mobile_money": qs.filter(payment_method=Sale.PaymentMethod.MOBILE_MONEY).aggregate(Sum("total_amount"))["total_amount__sum"] or 0,
            "other": qs.filter(payment_method=Sale.PaymentMethod.OTHER).aggregate(Sum("total_amount"))["total_amount__sum"] or 0,
        }

        # Top selling products
        top_products = (
            SaleItem.unscoped.filter(sale__tenant=tenant, sale__in=qs)
            .values("product__id", "product__name", "product__sku")
            .annotate(
                total_qty_sold=Sum("quantity"),
                total_revenue=Sum("total_price"),
                total_profit=Sum("profit"),
            )
            .order_by("-total_qty_sold")[:5]
        )

        return {
            "period": {
                "start_date": str(start_date) if start_date else "all_time",
                "end_date": str(end_date) if end_date else "all_time",
            },
            "summary": {
                "total_sales_count": aggregates["sales_count"] or 0,
                "total_revenue": str(aggregates["total_revenue"] or Decimal("0.00")),
                "total_cost_cogs": str(aggregates["total_cost"] or Decimal("0.00")),
                "total_profit": str(aggregates["total_profit"] or Decimal("0.00")),
                "total_tax_collected": str(aggregates["total_tax"] or Decimal("0.00")),
                "total_discount_given": str(aggregates["total_discount"] or Decimal("0.00")),
            },
            "payment_methods": {k: str(v) for k, v in payment_breakdown.items()},
            "top_selling_products": list(top_products),
        }
