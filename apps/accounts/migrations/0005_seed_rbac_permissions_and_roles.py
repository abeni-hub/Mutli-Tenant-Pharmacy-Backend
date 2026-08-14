from django.db import migrations

def seed_rbac_data(apps, schema_editor):
    PermissionCategory = apps.get_model("accounts", "PermissionCategory")
    Permission = apps.get_model("accounts", "Permission")
    Role = apps.get_model("accounts", "Role")

    categories_data = [
        {"key": "tenants", "name": "Tenant Management", "description": "Manage pharmacy tenant organizations and status", "order": 1},
        {"key": "users", "name": "User Management", "description": "Manage user accounts, invitations, and status", "order": 2},
        {"key": "roles", "name": "Role & Permission Management", "description": "Configure roles and assign permission capabilities", "order": 3},
        {"key": "subscriptions", "name": "Subscription Management", "description": "Oversee subscription plans, billing, and payments", "order": 4},
        {"key": "analytics", "name": "Revenue & Analytics", "description": "Platform revenue analytics and growth metrics", "order": 5},
        {"key": "reports", "name": "Platform Reports", "description": "Platform-wide operational and financial summaries", "order": 6},
        {"key": "flags", "name": "Feature Flags", "description": "Toggle system-wide feature flags and modules", "order": 7},
        {"key": "security", "name": "Security & Audit", "description": "Security logs, login history, and audit trails", "order": 8},
        {"key": "health", "name": "System Health", "description": "Infrastructure monitoring and subsystem health", "order": 9},
        {"key": "sales", "name": "Sales & POS Terminal", "description": "Point-of-sale terminal and invoice processing", "order": 10},
        {"key": "inventory", "name": "Inventory & Catalog", "description": "Medicine catalog, stock levels, and batch expiry", "order": 11},
        {"key": "purchases", "name": "Purchases & Suppliers", "description": "Supplier management and purchase orders", "order": 12},
    ]

    cat_map = {}
    for cat_dict in categories_data:
        cat_obj, _ = PermissionCategory.objects.get_or_create(
            key=cat_dict["key"],
            defaults={
                "name": cat_dict["name"],
                "description": cat_dict["description"],
                "order": cat_dict["order"],
            },
        )
        cat_map[cat_dict["key"]] = cat_obj

    permissions_data = [
        # Tenants
        {"key": "tenants.view", "name": "View Tenants", "description": "Allows viewing platform tenants and organizational details", "cat": "tenants", "scope": "global"},
        {"key": "tenants.create", "name": "Create Tenant", "description": "Allows registering new tenant organizations on the platform", "cat": "tenants", "scope": "global"},
        {"key": "tenants.suspend", "name": "Suspend Tenant", "description": "Allows suspending active tenant organizations", "cat": "tenants", "scope": "global"},
        {"key": "tenants.reactivate", "name": "Reactivate Tenant", "description": "Allows reactivating suspended tenant organizations", "cat": "tenants", "scope": "global"},
        {"key": "tenants.export", "name": "Export Tenants", "description": "Allows exporting tenant datasets and reports", "cat": "tenants", "scope": "global"},

        # Users
        {"key": "users.view", "name": "View Users", "description": "Allows viewing users and account profiles", "cat": "users", "scope": "global"},
        {"key": "users.invite", "name": "Invite Users", "description": "Allows inviting new users to the platform or tenant", "cat": "users", "scope": "global"},
        {"key": "users.activate", "name": "Activate User", "description": "Allows activating user accounts", "cat": "users", "scope": "global"},
        {"key": "users.deactivate", "name": "Deactivate User", "description": "Allows deactivating user accounts", "cat": "users", "scope": "global"},
        {"key": "users.change_role", "name": "Change User Role", "description": "Allows modifying assigned roles of users", "cat": "users", "scope": "global"},
        {"key": "users.reset_password", "name": "Reset Password", "description": "Allows issuing password reset tokens", "cat": "users", "scope": "global"},

        # Roles
        {"key": "roles.view", "name": "View Roles", "description": "Allows viewing roles and permission assignments", "cat": "roles", "scope": "global"},
        {"key": "roles.create", "name": "Create Role", "description": "Allows creating custom roles with selected permissions", "cat": "roles", "scope": "global"},
        {"key": "roles.update", "name": "Update Role", "description": "Allows updating custom role names and permissions", "cat": "roles", "scope": "global"},
        {"key": "roles.delete", "name": "Delete Role", "description": "Allows deleting custom roles", "cat": "roles", "scope": "global"},
        {"key": "roles.assign", "name": "Assign Role", "description": "Allows assigning roles to platform or tenant users", "cat": "roles", "scope": "global"},

        # Subscriptions
        {"key": "subscriptions.view", "name": "View Subscriptions", "description": "Allows viewing subscription plans and tenant subscription statuses", "cat": "subscriptions", "scope": "global"},
        {"key": "subscriptions.manage", "name": "Manage Subscriptions", "description": "Allows approving, rejecting, or updating subscription plans", "cat": "subscriptions", "scope": "global"},

        # Analytics
        {"key": "analytics.view", "name": "View Revenue Analytics", "description": "Allows viewing platform revenue metrics and growth analytics", "cat": "analytics", "scope": "global"},
        {"key": "analytics.export", "name": "Export Revenue Analytics", "description": "Allows exporting platform revenue analytics data", "cat": "analytics", "scope": "global"},

        # Reports
        {"key": "reports.view", "name": "View Reports", "description": "Allows viewing platform-wide reports", "cat": "reports", "scope": "global"},
        {"key": "reports.export", "name": "Export Reports", "description": "Allows downloading platform-wide report summaries", "cat": "reports", "scope": "global"},

        # Feature Flags
        {"key": "flags.view", "name": "View Feature Flags", "description": "Allows viewing feature flag configurations", "cat": "flags", "scope": "global"},
        {"key": "flags.toggle", "name": "Toggle Feature Flag", "description": "Allows enabling or disabling platform feature flags", "cat": "flags", "scope": "global"},
        {"key": "flags.export", "name": "Export Feature Flags", "description": "Allows exporting feature flag configurations", "cat": "flags", "scope": "global"},

        # Security
        {"key": "security.view", "name": "View Security Logs", "description": "Allows viewing security logs and audit trails", "cat": "security", "scope": "global"},
        {"key": "security.export", "name": "Export Security Logs", "description": "Allows exporting security audit logs", "cat": "security", "scope": "global"},

        # Health
        {"key": "health.view", "name": "View System Health", "description": "Allows monitoring server infrastructure and subsystem health", "cat": "health", "scope": "global"},
        {"key": "health.export", "name": "Export System Health", "description": "Allows exporting system infrastructure health status", "cat": "health", "scope": "global"},

        # Sales
        {"key": "sales.view", "name": "View Sales", "description": "Allows viewing sales transactions and invoices", "cat": "sales", "scope": "tenant"},
        {"key": "sales.create", "name": "Process New Sale", "description": "Allows processing new point-of-sale transactions", "cat": "sales", "scope": "tenant"},
        {"key": "sales.cancel", "name": "Cancel Sale", "description": "Allows cancelling or refunding completed sales", "cat": "sales", "scope": "tenant"},

        # Inventory
        {"key": "inventory.view", "name": "View Inventory", "description": "Allows viewing products, stock levels, and batch expiry dates", "cat": "inventory", "scope": "tenant"},
        {"key": "inventory.create", "name": "Add Product", "description": "Allows adding new products to the catalog", "cat": "inventory", "scope": "tenant"},
        {"key": "inventory.update", "name": "Update Product", "description": "Allows updating product details and stock balances", "cat": "inventory", "scope": "tenant"},
        {"key": "inventory.delete", "name": "Delete Product", "description": "Allows removing products from the catalog", "cat": "inventory", "scope": "tenant"},

        # Purchases
        {"key": "purchases.view", "name": "View Purchases", "description": "Allows viewing purchase orders and supplier catalogs", "cat": "purchases", "scope": "tenant"},
        {"key": "purchases.create", "name": "Create Purchase Order", "description": "Allows placing new purchase orders with suppliers", "cat": "purchases", "scope": "tenant"},
        {"key": "purchases.cancel", "name": "Cancel Purchase Order", "description": "Allows cancelling pending purchase orders", "cat": "purchases", "scope": "tenant"},
    ]

    perm_objs = []
    for p_dict in permissions_data:
        p_obj, _ = Permission.objects.get_or_create(
            key=p_dict["key"],
            defaults={
                "name": p_dict["name"],
                "description": p_dict["description"],
                "category": cat_map[p_dict["cat"]],
                "scope": p_dict["scope"],
                "is_system": True,
            },
        )
        perm_objs.append(p_obj)

    # Seed Default System Roles
    super_admin_role, _ = Role.objects.get_or_create(
        key="super_admin",
        defaults={
            "name": "Super Admin",
            "description": "Root SaaS platform administrator with full global privileges",
            "scope": "global",
            "is_system": True,
        },
    )
    super_admin_role.permissions.set(perm_objs)

    owner_role, _ = Role.objects.get_or_create(
        key="owner",
        defaults={
            "name": "Pharmacy Owner",
            "description": "Full administrative access within tenant pharmacy organization",
            "scope": "tenant",
            "is_system": True,
        },
    )
    owner_perms = [p for p in perm_objs if p.scope == "tenant"]
    owner_role.permissions.set(owner_perms)

    pharmacist_role, _ = Role.objects.get_or_create(
        key="pharmacist",
        defaults={
            "name": "Pharmacist",
            "description": "Dispensing, medicine verification, and inventory management capabilities",
            "scope": "tenant",
            "is_system": True,
        },
    )
    pharmacist_keys = ["sales.view", "sales.create", "inventory.view", "inventory.update"]
    pharmacist_role.permissions.set([p for p in perm_objs if p.key in pharmacist_keys])

    cashier_role, _ = Role.objects.get_or_create(
        key="cashier",
        defaults={
            "name": "Cashier",
            "description": "Point-of-sale checkout and receipt issuance",
            "scope": "tenant",
            "is_system": True,
        },
    )
    cashier_keys = ["sales.view", "sales.create"]
    cashier_role.permissions.set([p for p in perm_objs if p.key in cashier_keys])


def unseed_rbac_data(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_permissioncategory_permission_role_userrole'),
    ]

    operations = [
        migrations.RunPython(seed_rbac_data, unseed_rbac_data),
    ]
