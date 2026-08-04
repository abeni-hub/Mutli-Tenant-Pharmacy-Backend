from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import AuditService
from apps.catalog.models import Product
from apps.inventory.models import InventoryLog, StockBatch
from apps.inventory.services import InventoryService
from apps.purchases.models import GoodsReceipt, PurchaseOrder, PurchaseOrderItem, Supplier
from apps.tenants.models import Tenant


class PurchaseService:
    @staticmethod
    @transaction.atomic
    def create_purchase(*, tenant: Tenant, supplier: Supplier, data: dict[str, Any], performed_by=None) -> PurchaseOrder:
        if supplier.tenant_id != tenant.id:
            raise ValidationError({"supplier": "Supplier does not belong to this tenant."})

        po = PurchaseOrder.objects.create(
            tenant=tenant,
            po_number=data["po_number"],
            supplier=supplier,
            branch=data.get("branch", ""),
            warehouse=data.get("warehouse", ""),
            expected_delivery=data.get("expected_delivery"),
            notes=data.get("notes", ""),
            status=data.get("status", PurchaseOrder.Status.DRAFT),
            tax=data.get("tax", Decimal("0.00")),
            discount=data.get("discount", Decimal("0.00")),
        )

        item_total = Decimal("0.00")
        for item_data in data.get("items", []):
            product = item_data["product"]
            ordered_quantity = item_data["ordered_quantity"]
            unit_cost = item_data.get("unit_cost", Decimal("0.00"))
            discount = item_data.get("discount", Decimal("0.00"))
            tax = item_data.get("tax", Decimal("0.00"))
            line_total = unit_cost * ordered_quantity
            item_total += line_total
            PurchaseOrderItem.objects.create(
                tenant=tenant,
                purchase_order=po,
                product=product,
                ordered_quantity=ordered_quantity,
                received_quantity=0,
                unit_cost=unit_cost,
                discount=discount,
                tax=tax,
                total=line_total,
            )

        po.total = item_total
        po.save(update_fields=["total"])

        AuditService.record(
            tenant=tenant,
            actor=performed_by,
            action="create",
            entity_type="purchases.PurchaseOrder",
            entity_id=po.id,
            metadata={"po_number": po.po_number, "supplier_id": str(supplier.id)},
        )
        return po

    @staticmethod
    @transaction.atomic
    def approve_purchase(*, purchase_order: PurchaseOrder, performed_by=None) -> PurchaseOrder:
        if purchase_order.status == PurchaseOrder.Status.CANCELLED:
            raise ValidationError({"status": "Cancelled purchases cannot be approved."})
        if purchase_order.status != PurchaseOrder.Status.DRAFT:
            raise ValidationError({"status": "Purchase order is already processed."})

        purchase_order.status = PurchaseOrder.Status.APPROVED
        purchase_order.save(update_fields=["status"])
        AuditService.record(
            tenant=purchase_order.tenant,
            actor=performed_by,
            action="update",
            entity_type="purchases.PurchaseOrder",
            entity_id=purchase_order.id,
            metadata={"po_number": purchase_order.po_number, "action": "approve"},
        )
        return purchase_order

    @staticmethod
    @transaction.atomic
    def receive_purchase(*, purchase_order: PurchaseOrder, complete: bool = True, notes: str = "", performed_by=None) -> PurchaseOrder:
        if purchase_order.status == PurchaseOrder.Status.CANCELLED:
            raise ValidationError({"status": "Cancelled purchase orders cannot receive goods."})
        if purchase_order.status not in {PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.SENT}:
            raise ValidationError({"status": "Only approved or sent purchase orders can receive goods."})

        purchase_order.status = PurchaseOrder.Status.RECEIVED
        purchase_order.save(update_fields=["status"])

        receipt = GoodsReceipt.objects.create(
            tenant=purchase_order.tenant,
            purchase_order=purchase_order,
            receipt_number=f"GRN-{purchase_order.po_number}",
            notes=notes,
            complete=complete,
        )

        for item in purchase_order.items.select_related("product").all():
            batch_number = f"BATCH-{purchase_order.po_number}-{item.product.sku}"
            batch = InventoryService.stock_in(
                tenant=purchase_order.tenant,
                product=item.product,
                batch_number=batch_number,
                quantity=item.ordered_quantity,
                expiry_date=timezone.now().date() + timedelta(days=365),
                unit_price=item.unit_cost,
                selling_price=item.product.selling_price or Decimal("0.00"),
                supplier=purchase_order.supplier.company_name,
                purchase_order_reference=purchase_order.po_number,
                warehouse=purchase_order.warehouse,
                branch=purchase_order.branch,
                notes=notes,
                reference_number=purchase_order.po_number,
                performed_by=performed_by,
            )
            item.received_quantity = item.ordered_quantity
            item.save(update_fields=["received_quantity"])
            receipt.batch = batch
            receipt.save(update_fields=["batch"])

        AuditService.record(
            tenant=purchase_order.tenant,
            actor=performed_by,
            action="update",
            entity_type="purchases.PurchaseOrder",
            entity_id=purchase_order.id,
            metadata={"po_number": purchase_order.po_number, "action": "receive"},
        )
        return purchase_order

    @staticmethod
    @transaction.atomic
    def cancel_purchase(*, purchase_order: PurchaseOrder, reason: str = "", performed_by=None) -> PurchaseOrder:
        if purchase_order.status == PurchaseOrder.Status.RECEIVED:
            raise ValidationError({"status": "Received purchase orders cannot be cancelled."})
        purchase_order.status = PurchaseOrder.Status.CANCELLED
        purchase_order.save(update_fields=["status"])
        AuditService.record(
            tenant=purchase_order.tenant,
            actor=performed_by,
            action="update",
            entity_type="purchases.PurchaseOrder",
            entity_id=purchase_order.id,
            metadata={"po_number": purchase_order.po_number, "action": "cancel"},
        )
        return purchase_order

    @staticmethod
    def get_summary(tenant: Tenant) -> dict[str, Any]:
        orders = PurchaseOrder.unscoped.filter(tenant=tenant)
        return {
            "total_purchases": orders.count(),
            "draft_purchases": orders.filter(status=PurchaseOrder.Status.DRAFT).count(),
            "approved_purchases": orders.filter(status=PurchaseOrder.Status.APPROVED).count(),
            "received_purchases": orders.filter(status=PurchaseOrder.Status.RECEIVED).count(),
            "cancelled_purchases": orders.filter(status=PurchaseOrder.Status.CANCELLED).count(),
            "total_value": str(orders.aggregate(total=Sum("total"))["total"] or Decimal("0.00")),
        }

    @staticmethod
    def get_supplier_performance(tenant: Tenant) -> list[dict[str, Any]]:
        suppliers = Supplier.unscoped.filter(tenant=tenant).prefetch_related("purchase_orders")
        data = []
        for supplier in suppliers:
            orders = supplier.purchase_orders.filter(status=PurchaseOrder.Status.RECEIVED)
            data.append(
                {
                    "supplier": supplier.company_name,
                    "purchase_count": orders.count(),
                    "total_spend": str(orders.aggregate(total=Sum("total"))["total"] or Decimal("0.00")),
                }
            )
        return data

    @staticmethod
    def get_trends(tenant: Tenant) -> list[dict[str, Any]]:
        return []

    @staticmethod
    def get_purchase_costs(tenant: Tenant) -> list[dict[str, Any]]:
        return []

    @staticmethod
    def get_outstanding_purchase_orders(tenant: Tenant) -> list[dict[str, Any]]:
        orders = PurchaseOrder.unscoped.filter(tenant=tenant, status__in=[PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.SENT]).prefetch_related("supplier")
        return [{"po_number": order.po_number, "supplier": order.supplier.company_name, "status": order.status, "total": str(order.total)} for order in orders]

    @staticmethod
    def get_received_orders(tenant: Tenant) -> list[dict[str, Any]]:
        orders = PurchaseOrder.unscoped.filter(tenant=tenant, status=PurchaseOrder.Status.RECEIVED).prefetch_related("supplier")
        return [{"po_number": order.po_number, "supplier": order.supplier.company_name, "status": order.status, "total": str(order.total)} for order in orders]

    @staticmethod
    def get_supplier_spend(tenant: Tenant) -> list[dict[str, Any]]:
        return PurchaseService.get_supplier_performance(tenant)
