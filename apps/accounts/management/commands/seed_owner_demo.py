from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import uuid

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.catalog.models import Product
from apps.inventory.models import StockBatch
from apps.purchases.models import PurchaseOrder, PurchaseOrderItem, Supplier
from apps.sales.models import Sale, SaleItem
from apps.subscriptions.models import SubscriptionPlan, TenantSubscription
from apps.tenants.models import Branch, Membership, Tenant


class Command(BaseCommand):
    help = "Idempotently seed test data for Owner tenant workspace & dashboard verification."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding Owner demo data..."))

        # 1. Ensure Plan
        plan, _ = SubscriptionPlan.objects.get_or_create(
            code=SubscriptionPlan.Code.ENTERPRISE,
            defaults={
                "name": "Enterprise",
                "description": "Unlimited full enterprise pharmacy solution",
                "price_monthly": Decimal("199.00"),
                "price_yearly": Decimal("1990.00"),
                "max_users": -1,
                "max_medicines": -1,
                "max_branches": -1,
                "has_reports": True,
                "has_sms": True,
                "has_backups": True,
            },
        )

        # 2. Ensure Tenant
        tenant_name = "Abeni Pharmacy"
        tenant_slug = "abeni-pharmacy"
        tenant, _ = Tenant.objects.get_or_create(
            slug=tenant_slug,
            defaults={
                "name": tenant_name,
                "registration_number": "ACP-4402",
                "is_active": True,
            },
        )
        if not tenant.is_active:
            tenant.is_active = True
            tenant.save(update_fields=["is_active"])

        # Subscription
        now = timezone.now()
        TenantSubscription.objects.update_or_create(
            tenant=tenant,
            defaults={
                "plan": plan,
                "status": TenantSubscription.Status.ACTIVE,
                "billing_cycle": TenantSubscription.BillingCycle.YEARLY,
                "starts_at": now - timedelta(days=60),
                "expires_at": now + timedelta(days=305),
                "auto_renew": True,
            },
        )

        # 3. Ensure Branches
        main_branch, _ = Branch.objects.update_or_create(
            tenant=tenant,
            code="ACP-MAIN",
            defaults={
                "name": "Main Branch",
                "address": "Kazanchis, Addis Ababa",
                "phone": "+251911000003",
                "is_main": True,
                "is_active": True,
            },
        )
        bole_branch, _ = Branch.objects.update_or_create(
            tenant=tenant,
            code="ACP-BOLE",
            defaults={
                "name": "Bole Branch",
                "address": "Bole Road, Addis Ababa",
                "phone": "+251911000004",
                "is_main": False,
                "is_active": True,
            },
        )

        # 4. Ensure Owner Account
        owner_email = "owner@abeni.test"
        owner, created = User.objects.get_or_create(
            email=owner_email,
            defaults={
                "first_name": "Abeni",
                "last_name": "Owner",
                "is_active": True,
            },
        )
        if created or not owner.check_password("SecurePassword123!"):
            owner.set_password("SecurePassword123!")
            owner.save()

        Membership.objects.update_or_create(
            tenant=tenant,
            user=owner,
            defaults={"role": Membership.Role.OWNER, "is_active": True},
        )

        # Staff Members
        staff_data = [
            ("pharmacist@abeni.test", "Tadesse", "Pharmacist", Membership.Role.PHARMACIST),
            ("cashier@abeni.test", "Betelehem", "Cashier", Membership.Role.CASHIER),
        ]
        cashier_user = None
        for email, fn, ln, role in staff_data:
            st_user, st_created = User.objects.get_or_create(
                email=email,
                defaults={"first_name": fn, "last_name": ln, "is_active": True},
            )
            if st_created or not st_user.check_password("SecurePassword123!"):
                st_user.set_password("SecurePassword123!")
                st_user.save()
            Membership.objects.update_or_create(
                tenant=tenant,
                user=st_user,
                defaults={"role": role, "is_active": True},
            )
            if role == Membership.Role.CASHIER:
                cashier_user = st_user

        # 5. Suppliers
        suppliers_specs = [
            {"company_name": "MedPharma Distributors", "code": "SUP-001", "contact_person": "Abebe Bekele", "email": "contact@medpharma.test", "phone": "+251911223344"},
            {"company_name": "Global Healthcare Ltd", "code": "SUP-002", "contact_person": "Sara Haile", "email": "orders@globalhealth.test", "phone": "+251911556677"},
            {"company_name": "PharmaCare Supplies", "code": "SUP-003", "contact_person": "Yonas Tilahun", "email": "sales@pharmacare.test", "phone": "+251911889900"},
        ]
        suppliers_dict = {}
        for sspec in suppliers_specs:
            sup = Supplier.unscoped.filter(tenant=tenant, code=sspec["code"]).first()
            if sup:
                for k, v in sspec.items():
                    setattr(sup, k, v)
                sup.save()
            else:
                sup = Supplier.objects.create(tenant=tenant, **sspec)
            suppliers_dict[sspec["code"]] = sup



        # 7. Products (At least 12 products across 6 pharmacy categories)
        products_specs = [
            {"name": "Amoxicillin 500mg Capsule", "sku": "AMX-500-CAP", "category": "Antibiotics", "unit_of_measure": "Box", "reorder_level": 20},
            {"name": "Azithromycin 250mg Tablet", "sku": "AZT-250-TAB", "category": "Antibiotics", "unit_of_measure": "Blister", "reorder_level": 15},
            {"name": "Ciprofloxacin 500mg Tablet", "sku": "CIP-500-TAB", "category": "Antibiotics", "unit_of_measure": "Box", "reorder_level": 10},

            {"name": "Paracetamol 500mg Tablet", "sku": "PCM-500-TAB", "category": "Analgesics", "unit_of_measure": "Strip", "reorder_level": 50},
            {"name": "Ibuprofen 400mg Tablet", "sku": "IBU-400-TAB", "category": "Analgesics", "unit_of_measure": "Box", "reorder_level": 25},
            {"name": "Tramadol 50mg Capsule", "sku": "TRM-050-CAP", "category": "Analgesics", "unit_of_measure": "Box", "reorder_level": 10},

            {"name": "Vitamin C 1000mg Effervescent", "sku": "VTC-1000-EFF", "category": "Vitamins", "unit_of_measure": "Tube", "reorder_level": 30},
            {"name": "Multivitamin Complex", "sku": "MVT-CMP-TAB", "category": "Vitamins", "unit_of_measure": "Bottle", "reorder_level": 20},

            {"name": "Amlodipine 5mg Tablet", "sku": "AML-005-TAB", "category": "Antihypertensives", "unit_of_measure": "Box", "reorder_level": 15},
            {"name": "Enalapril 10mg Tablet", "sku": "ENL-010-TAB", "category": "Antihypertensives", "unit_of_measure": "Box", "reorder_level": 10},

            {"name": "Metformin 500mg Tablet", "sku": "MTF-500-TAB", "category": "Diabetes", "unit_of_measure": "Box", "reorder_level": 20},
            {"name": "Glibenclamide 5mg Tablet", "sku": "GLB-005-TAB", "category": "Diabetes", "unit_of_measure": "Box", "reorder_level": 10},

            {"name": "Omeprazole 20mg Capsule", "sku": "OMP-020-CAP", "category": "Gastrointestinal", "unit_of_measure": "Box", "reorder_level": 25},
            {"name": "Antacid Liquid Suspension 200ml", "sku": "ANT-200-LIQ", "category": "Gastrointestinal", "unit_of_measure": "Bottle", "reorder_level": 15},
        ]

        products_dict = {}
        for pspec in products_specs:
            prod = Product.unscoped.filter(tenant=tenant, sku=pspec["sku"]).first()
            if prod:
                prod.name = pspec["name"]
                prod.category = pspec["category"]
                prod.unit = pspec["unit_of_measure"]
                prod.reorder_level = pspec["reorder_level"]
                prod.is_active = True
                prod.save()
            else:
                prod = Product.objects.create(
                    tenant=tenant,
                    sku=pspec["sku"],
                    name=pspec["name"],
                    category=pspec["category"],
                    unit=pspec["unit_of_measure"],
                    reorder_level=pspec["reorder_level"],
                    is_active=True,
                )
            products_dict[pspec["sku"]] = prod

        # 8. Batches (Normal, Low Stock, Near Expiry, Expired)
        today_date = timezone.now().date()
        batches_specs = [
            # Normal stock
            {"sku": "AMX-500-CAP", "batch_number": "B-AMX-2026-01", "quantity": 120, "expiry": today_date + timedelta(days=400), "u_price": "3.50", "s_price": "8.00", "branch": main_branch},
            {"sku": "PCM-500-TAB", "batch_number": "B-PCM-2026-01", "quantity": 350, "expiry": today_date + timedelta(days=500), "u_price": "1.00", "s_price": "2.50", "branch": main_branch},
            {"sku": "VTC-1000-EFF", "batch_number": "B-VTC-2026-01", "quantity": 90, "expiry": today_date + timedelta(days=300), "u_price": "4.00", "s_price": "9.50", "branch": main_branch},
            {"sku": "AML-005-TAB", "batch_number": "B-AML-2026-01", "quantity": 60, "expiry": today_date + timedelta(days=360), "u_price": "2.00", "s_price": "5.00", "branch": main_branch},

            # Low stock
            {"sku": "CIP-500-TAB", "batch_number": "B-CIP-2026-01", "quantity": 4, "expiry": today_date + timedelta(days=250), "u_price": "5.00", "s_price": "12.00", "branch": main_branch},
            {"sku": "TRM-050-CAP", "batch_number": "B-TRM-2026-01", "quantity": 5, "expiry": today_date + timedelta(days=200), "u_price": "6.00", "s_price": "14.00", "branch": main_branch},

            # Near expiry (expiring in 25-45 days)
            {"sku": "AZT-250-TAB", "batch_number": "B-AZT-2026-EXP", "quantity": 30, "expiry": today_date + timedelta(days=30), "u_price": "4.50", "s_price": "10.00", "branch": main_branch},
            {"sku": "ENL-010-TAB", "batch_number": "B-ENL-2026-EXP", "quantity": 18, "expiry": today_date + timedelta(days=40), "u_price": "2.50", "s_price": "6.00", "branch": main_branch},

            # Expired stock
            {"sku": "GLB-005-TAB", "batch_number": "B-GLB-2025-OLD", "quantity": 15, "expiry": today_date - timedelta(days=10), "u_price": "1.50", "s_price": "4.00", "branch": main_branch},
        ]

        for bspec in batches_specs:
            prod = products_dict[bspec["sku"]]
            sb = StockBatch.unscoped.filter(tenant=tenant, batch_number=bspec["batch_number"]).first()
            if sb:
                sb.product = prod
                sb.branch = bspec["branch"].name
                sb.quantity = bspec["quantity"]
                sb.expiry_date = bspec["expiry"]
                sb.unit_price = Decimal(bspec["u_price"])
                sb.selling_price = Decimal(bspec["s_price"])
                sb.supplier = "MedPharma Distributors"
                sb.is_active = True
                sb.save()
            else:
                StockBatch.objects.create(
                    tenant=tenant,
                    batch_number=bspec["batch_number"],
                    product=prod,
                    branch=bspec["branch"].name,
                    quantity=bspec["quantity"],
                    expiry_date=bspec["expiry"],
                    unit_price=Decimal(bspec["u_price"]),
                    selling_price=Decimal(bspec["s_price"]),
                    supplier="MedPharma Distributors",
                    is_active=True,
                )

        # 9. Purchases
        po1 = PurchaseOrder.unscoped.filter(tenant=tenant, po_number="PO-2026-0001").first()
        if not po1:
            PurchaseOrder.objects.create(
                tenant=tenant,
                po_number="PO-2026-0001",
                supplier=suppliers_dict["SUP-001"],
                branch=main_branch.name,
                status=PurchaseOrder.Status.DRAFT,
                total=Decimal("450.00"),
                notes="Restock antibiotics and analgesics",
            )

        po2 = PurchaseOrder.unscoped.filter(tenant=tenant, po_number="PO-2026-0002").first()
        if not po2:
            PurchaseOrder.objects.create(
                tenant=tenant,
                po_number="PO-2026-0002",
                supplier=suppliers_dict["SUP-002"],
                branch=main_branch.name,
                status=PurchaseOrder.Status.APPROVED,
                total=Decimal("820.00"),
                notes="Monthly vitamin and antihypertensive order",
            )

        # 10. Sales Transactions (Historical & Today's Sales)
        amx_prod = products_dict["AMX-500-CAP"]
        pcm_prod = products_dict["PCM-500-TAB"]
        vtc_prod = products_dict["VTC-1000-EFF"]

        # Today's sale
        today_sale, created_ts = Sale.unscoped.get_or_create(
            tenant=tenant,
            invoice_number="REC-20260814-0001",
            defaults={
                "branch": main_branch.name,
                "cashier": cashier_user or owner,
                "customer_name": "Almaz Tadesse",
                "customer_phone": "+251911123456",
                "subtotal": Decimal("180.00"),
                "discount_amount": Decimal("10.00"),
                "tax_amount": Decimal("25.50"),
                "total_amount": Decimal("195.50"),
                "total_cost": Decimal("75.00"),
                "total_profit": Decimal("120.50"),
                "payment_method": Sale.PaymentMethod.CASH,
                "status": Sale.Status.COMPLETED,
            },
        )
        if created_ts:
            amx_batch = StockBatch.unscoped.filter(tenant=tenant, product=amx_prod).first()
            vtc_batch = StockBatch.unscoped.filter(tenant=tenant, product=vtc_prod).first()
            if amx_batch:
                SaleItem.objects.create(
                    tenant=tenant,
                    sale=today_sale,
                    product=amx_prod,
                    batch=amx_batch,
                    quantity=10,
                    unit_selling_price=Decimal("8.00"),
                    unit_cost_price=Decimal("3.50"),
                    total_cost=Decimal("35.00"),
                    total_price=Decimal("80.00"),
                    profit=Decimal("45.00"),
                )
            if vtc_batch:
                SaleItem.objects.create(
                    tenant=tenant,
                    sale=today_sale,
                    product=vtc_prod,
                    batch=vtc_batch,
                    quantity=10,
                    unit_selling_price=Decimal("10.00"),
                    unit_cost_price=Decimal("4.00"),
                    total_cost=Decimal("40.00"),
                    total_price=Decimal("100.00"),
                    profit=Decimal("60.00"),
                )

        # Yesterday's sale
        yesterday_date = now - timedelta(days=1)
        yst_sale, created_ys = Sale.unscoped.get_or_create(
            tenant=tenant,
            invoice_number="REC-20260813-0002",
            defaults={
                "branch": main_branch.name,
                "cashier": cashier_user or owner,
                "customer_name": "Kebede Chala",
                "customer_phone": "+251911987654",
                "subtotal": Decimal("250.00"),
                "discount_amount": Decimal("0.00"),
                "tax_amount": Decimal("37.50"),
                "total_amount": Decimal("287.50"),
                "total_cost": Decimal("100.00"),
                "total_profit": Decimal("187.50"),
                "payment_method": Sale.PaymentMethod.MOBILE_MONEY,
                "status": Sale.Status.COMPLETED,
                "created_at": yesterday_date,
            },
        )

        # 11. Audit Events
        AuditEvent.objects.get_or_create(
            tenant=tenant,
            action=AuditEvent.Action.LOGIN,
            entity_type="Auth",
            entity_id=owner.id,
            defaults={
                "actor": owner,
                "metadata": {"ip": "127.0.0.1", "description": f"Owner {owner_email} logged in successfully."},
            },
        )
        AuditEvent.objects.get_or_create(
            tenant=tenant,
            action=AuditEvent.Action.CREATE,
            entity_type="StockBatch",
            entity_id=tenant.id,
            defaults={
                "actor": owner,
                "metadata": {"description": "Stock batch B-AMX-2026-01 added to inventory."},
            },
        )

        self.stdout.write(self.style.SUCCESS("Successfully seeded Owner demo data!"))
