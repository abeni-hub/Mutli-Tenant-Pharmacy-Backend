from django.core.management.base import BaseCommand
from django.db import transaction
from apps.accounts.models import PermissionCategory, Permission, Role

CATEGORIES = [
    {
        "key": "tenants",
        "name": "Tenant Management",
        "description": "Tenant lifecycle, provisioning, and configuration",
        "order": 10,
    },
    {
        "key": "users",
        "name": "User & Staff Management",
        "description": "User accounts, staff invitations, and role assignments",
        "order": 20,
    },
    {
        "key": "roles",
        "name": "Roles & Permissions",
        "description": "Custom role creation and permission delegation",
        "order": 30,
    },
    {
        "key": "subscriptions",
        "name": "Subscriptions & Billing",
        "description": "Subscription plans, feature tiers, and billing",
        "order": 40,
    },
    {
        "key": "catalog",
        "name": "Products & Catalog",
        "description": "Pharmacy product catalog, pricing, and master list",
        "order": 50,
    },
    {
        "key": "inventory",
        "name": "Inventory & Batches",
        "description": "Stock batch management, expiry tracking, and adjustments",
        "order": 60,
    },
    {
        "key": "sales",
        "name": "Sales & Checkout POS",
        "description": "Point-of-sale terminal, receipts, and order processing",
        "order": 70,
    },
    {
        "key": "purchasing",
        "name": "Purchasing & Suppliers",
        "description": "Supplier management, purchase orders, and receiving",
        "order": 80,
    },
    {
        "key": "reports",
        "name": "Financials & Reports",
        "description": "Revenue analytics, financial reports, and data exports",
        "order": 90,
    },
    {
        "key": "security",
        "name": "Security & Audit",
        "description": "Audit logs, login history, and security policies",
        "order": 100,
    },
    {
        "key": "system",
        "name": "Platform & System",
        "description": "Global feature flags, system monitoring, and health",
        "order": 110,
    },
]

PERMISSIONS = [
    # Global Scope
    {"key": "tenants.view", "name": "View Tenants", "cat": "tenants", "scope": "global"},
    {"key": "tenants.create", "name": "Create Tenant", "cat": "tenants", "scope": "global"},
    {"key": "tenants.update", "name": "Update Tenant", "cat": "tenants", "scope": "global"},
    {"key": "tenants.delete", "name": "Delete Tenant", "cat": "tenants", "scope": "global"},
    {"key": "subscriptions.manage", "name": "Manage Global Subscription Plans", "cat": "subscriptions", "scope": "global"},
    {"key": "platform.analytics", "name": "View Global Revenue Analytics", "cat": "reports", "scope": "global"},
    {"key": "platform.feature_flags", "name": "Manage Global Feature Flags", "cat": "system", "scope": "global"},
    {"key": "platform.audit", "name": "View Global Audit Logs", "cat": "security", "scope": "global"},
    {"key": "platform.system_health", "name": "View Platform System Health", "cat": "system", "scope": "global"},

    # Tenant Scope
    {"key": "users.view", "name": "View Tenant Users", "cat": "users", "scope": "tenant"},
    {"key": "users.create", "name": "Create Tenant User", "cat": "users", "scope": "tenant"},
    {"key": "users.invite", "name": "Invite Tenant User", "cat": "users", "scope": "tenant"},
    {"key": "users.update", "name": "Update Tenant User", "cat": "users", "scope": "tenant"},
    {"key": "users.delete", "name": "Delete Tenant User", "cat": "users", "scope": "tenant"},

    {"key": "roles.view", "name": "View Tenant Roles", "cat": "roles", "scope": "tenant"},
    {"key": "roles.create", "name": "Create Tenant Custom Role", "cat": "roles", "scope": "tenant"},
    {"key": "roles.update", "name": "Update Tenant Custom Role", "cat": "roles", "scope": "tenant"},
    {"key": "roles.delete", "name": "Delete Tenant Custom Role", "cat": "roles", "scope": "tenant"},

    {"key": "products.view", "name": "View Products Catalog", "cat": "catalog", "scope": "tenant"},
    {"key": "products.create", "name": "Create Product", "cat": "catalog", "scope": "tenant"},
    {"key": "products.update", "name": "Update Product", "cat": "catalog", "scope": "tenant"},
    {"key": "products.delete", "name": "Delete Product", "cat": "catalog", "scope": "tenant"},

    {"key": "inventory.view", "name": "View Inventory Batches", "cat": "inventory", "scope": "tenant"},
    {"key": "inventory.adjust", "name": "Adjust Stock & Transfer", "cat": "inventory", "scope": "tenant"},
    {"key": "inventory.dispense", "name": "Dispense Medicine", "cat": "inventory", "scope": "tenant"},

    {"key": "sales.view", "name": "View Sales History", "cat": "sales", "scope": "tenant"},
    {"key": "sales.create", "name": "Process POS Sale", "cat": "sales", "scope": "tenant"},

    {"key": "purchases.view", "name": "View Purchase Orders", "cat": "purchasing", "scope": "tenant"},
    {"key": "purchases.create", "name": "Create Purchase Order", "cat": "purchasing", "scope": "tenant"},
    {"key": "suppliers.manage", "name": "Manage Suppliers", "cat": "purchasing", "scope": "tenant"},

    {"key": "reports.view", "name": "View Tenant Reports", "cat": "reports", "scope": "tenant"},
    {"key": "reports.export", "name": "Generate Tenant Data Exports", "cat": "reports", "scope": "tenant"},

    {"key": "security.view", "name": "View Tenant Audit Logs", "cat": "security", "scope": "tenant"},
    {"key": "settings.manage", "name": "Manage Tenant Settings", "cat": "system", "scope": "tenant"},
]

SYSTEM_ROLES = [
    {
        "key": "super_admin",
        "name": "Super Admin",
        "description": "Global system owner with unrestricted platform authority",
        "scope": "global",
        "all_global": True,
        "all_tenant": True,
    },
    {
        "key": "owner",
        "name": "Owner",
        "description": "Tenant administrator with full capabilities within their company",
        "scope": "tenant",
        "all_global": False,
        "all_tenant": True,
    },
    {
        "key": "pharmacist",
        "name": "Pharmacist",
        "description": "Clinical & dispensing staff for prescription verification and medicine inventory",
        "scope": "tenant",
        "all_global": False,
        "permission_keys": [
            "products.view",
            "products.create",
            "products.update",
            "inventory.view",
            "inventory.adjust",
            "inventory.dispense",
            "sales.view",
        ],
    },
    {
        "key": "cashier",
        "name": "Cashier",
        "description": "Checkout and sales terminal operator for processing transactions",
        "scope": "tenant",
        "all_global": False,
        "permission_keys": [
            "products.view",
            "sales.view",
            "sales.create",
        ],
    },
]

class Command(BaseCommand):
    help = "Seed RBAC permission categories, permissions, and system roles."

    def handle(self, *args, **options):
        self.stdout.write("Seeding RBAC Categories, Permissions, and System Roles...")

        with transaction.atomic():
            # 1. Seed Categories
            category_objs = {}
            for cat_data in CATEGORIES:
                cat, _ = PermissionCategory.objects.update_or_create(
                    key=cat_data["key"],
                    defaults={
                        "name": cat_data["name"],
                        "description": cat_data["description"],
                        "order": cat_data["order"],
                    },
                )
                category_objs[cat_data["key"]] = cat

            # 2. Seed Permissions
            perm_objs = {}
            for p_data in PERMISSIONS:
                cat = category_objs[p_data["cat"]]
                perm, _ = Permission.objects.update_or_create(
                    key=p_data["key"],
                    defaults={
                        "name": p_data["name"],
                        "category": cat,
                        "scope": p_data["scope"],
                        "is_system": True,
                    },
                )
                perm_objs[p_data["key"]] = perm

            # 3. Seed System Roles
            for r_data in SYSTEM_ROLES:
                role, _ = Role.objects.update_or_create(
                    key=r_data["key"],
                    defaults={
                        "name": r_data["name"],
                        "description": r_data["description"],
                        "scope": r_data["scope"],
                        "is_system": True,
                    },
                )

                if r_data.get("all_global") and r_data.get("all_tenant"):
                    role.permissions.set(Permission.objects.all())
                elif r_data.get("all_tenant"):
                    tenant_perms = Permission.objects.filter(scope="tenant")
                    role.permissions.set(tenant_perms)
                elif "permission_keys" in r_data:
                    assigned = [perm_objs[k] for k in r_data["permission_keys"] if k in perm_objs]
                    role.permissions.set(assigned)

        self.stdout.write(self.style.SUCCESS("Successfully seeded RBAC Permissions & System Roles!"))
