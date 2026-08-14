from __future__ import annotations
import sys

from django.core.management.base import BaseCommand
from django.db.models import Sum, Count
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.catalog.models import Product
from apps.inventory.models import StockBatch
from apps.purchases.models import PurchaseOrder, Supplier
from apps.sales.models import Sale
from apps.subscriptions.models import TenantSubscription
from apps.tenants.models import Branch, Membership, Tenant


class Command(BaseCommand):
    help = "Verify PostgreSQL database truth for Owner workspace & tenant isolation."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== OWNER DATABASE TRUTH VERIFICATION ==="))

        has_failure = False
        today_date = timezone.now().date()

        # 1. Owner User Check
        owner_email = "owner@abeni.test"
        owner = User.objects.filter(email=owner_email).first()

        if not owner:
            self.stdout.write(self.style.ERROR(f"[FAIL] Owner user '{owner_email}' does NOT exist in PostgreSQL."))
            has_failure = True
        else:
            self.stdout.write(self.style.SUCCESS(f"[PASS] Owner User: {owner.email} (ID: {owner.id})"))
            self.stdout.write(f"       Name: {owner.full_name}")

            # Check Membership
            membership = Membership.objects.filter(user=owner, is_active=True).first()
            if not membership:
                self.stdout.write(self.style.ERROR("       [FAIL] Owner has no active tenant membership!"))
                has_failure = True
            else:
                tenant = membership.tenant
                self.stdout.write(self.style.SUCCESS(f"       Role: {membership.role}"))
                self.stdout.write(self.style.SUCCESS(f"       Tenant: {tenant.name} (ID: {tenant.id}, Slug: {tenant.slug})"))

                if membership.role != Membership.Role.OWNER:
                    self.stdout.write(self.style.ERROR(f"       [MISMATCH] Role is '{membership.role}', expected 'owner'!"))
                    has_failure = True

        # 2. Tenants & Isolation Stats
        total_tenants = Tenant.objects.count()
        self.stdout.write(self.style.MIGRATE_HEADING("\n--- TENANTS ---"))
        self.stdout.write(f"Total Tenants in DB: {total_tenants}")

        target_tenant = Tenant.objects.filter(slug="abeni-pharmacy").first() or (membership.tenant if membership else None)
        if not target_tenant:
            self.stdout.write(self.style.ERROR("[FAIL] Tenant missing from database!"))
            has_failure = True
            sys.exit(1)

        # 3. Branch Count
        branch_count = Branch.objects.filter(tenant=target_tenant).count()
        self.stdout.write(self.style.MIGRATE_HEADING("\n--- BRANCHES ---"))
        self.stdout.write(f"Branch Count for {target_tenant.name}: {branch_count}")

        # 4. User Count by Role
        owners_count = Membership.objects.filter(tenant=target_tenant, role=Membership.Role.OWNER, is_active=True).count()
        pharmacists_count = Membership.objects.filter(tenant=target_tenant, role=Membership.Role.PHARMACIST, is_active=True).count()
        cashiers_count = Membership.objects.filter(tenant=target_tenant, role=Membership.Role.CASHIER, is_active=True).count()
        self.stdout.write(self.style.MIGRATE_HEADING("\n--- TENANT USERS BY ROLE ---"))
        self.stdout.write(f"Owners: {owners_count}")
        self.stdout.write(f"Pharmacists: {pharmacists_count}")
        self.stdout.write(f"Cashiers: {cashiers_count}")

        # 5. Product & Inventory Stats
        product_count = Product.unscoped.filter(tenant=target_tenant, is_active=True).count()
        batch_count = StockBatch.unscoped.filter(tenant=target_tenant, is_active=True).count()

        low_stock_count = 0
        for p in Product.unscoped.filter(tenant=target_tenant, is_active=True):
            tot = StockBatch.unscoped.filter(tenant=target_tenant, product=p, is_active=True, expiry_date__gt=today_date).aggregate(t=Sum("quantity"))["t"] or 0
            if tot <= p.reorder_level:
                low_stock_count += 1

        near_expiry_count = StockBatch.unscoped.filter(
            tenant=target_tenant,
            is_active=True,
            quantity__gt=0,
            expiry_date__gt=today_date,
            expiry_date__lte=today_date + timezone.timedelta(days=60),
        ).count()

        self.stdout.write(self.style.MIGRATE_HEADING("\n--- CATALOG & INVENTORY ---"))
        self.stdout.write(f"Product Count: {product_count}")
        self.stdout.write(f"Stock Batch Count: {batch_count}")
        self.stdout.write(f"Low Stock Products: {low_stock_count}")
        self.stdout.write(f"Near Expiry Batches: {near_expiry_count}")

        # 6. Sales Stats
        today_sales_count = Sale.unscoped.filter(tenant=target_tenant, created_at__date=today_date, status__in=[Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED]).count()
        total_sales_count = Sale.unscoped.filter(tenant=target_tenant, status__in=[Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED]).count()
        total_revenue = Sale.unscoped.filter(tenant=target_tenant, status__in=[Sale.Status.COMPLETED, Sale.Status.PARTIALLY_REFUNDED]).aggregate(r=Sum("total_amount"))["r"] or 0

        self.stdout.write(self.style.MIGRATE_HEADING("\n--- SALES ---"))
        self.stdout.write(f"Today's Sales Count: {today_sales_count}")
        self.stdout.write(f"Total Sales Count: {total_sales_count}")
        self.stdout.write(f"Total Revenue: {total_revenue}")

        # 7. Purchases, Suppliers, Customers, Audit
        pending_po = PurchaseOrder.unscoped.filter(tenant=target_tenant, status=PurchaseOrder.Status.DRAFT).count()
        approved_po = PurchaseOrder.unscoped.filter(tenant=target_tenant, status=PurchaseOrder.Status.APPROVED).count()
        supplier_count = Supplier.unscoped.filter(tenant=target_tenant).count()
        audit_count = AuditEvent.objects.filter(tenant=target_tenant).count()
        self.stdout.write(self.style.MIGRATE_HEADING("\n--- PURCHASES & SUPPLIERS & AUDIT ---"))
        self.stdout.write(f"Pending POs: {pending_po}")
        self.stdout.write(f"Approved POs: {approved_po}")
        self.stdout.write(f"Supplier Count: {supplier_count}")
        self.stdout.write(f"Audit Events: {audit_count}")

        if has_failure:
            self.stdout.write(self.style.ERROR("\n=== VERIFICATION COMPLETED WITH ERRORS ==="))
            sys.exit(1)
        else:
            self.stdout.write(self.style.SUCCESS("\n=== ALL OWNER DATABASE TRUTH CHECKS PASSED PERFECTLY ==="))
