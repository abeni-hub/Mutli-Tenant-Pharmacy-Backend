"""
Custom DRF permission classes for the multi-tenant pharmacy system.

Architecture
────────────
• TenantMembershipPermission — base: requires a valid X-Tenant-ID header and
  an active Membership for the current user.  Sets the TenantContext.

• TenantRolePermission — base: extends TenantMembershipPermission to also
  enforce that the user holds one of the required_roles.

• Role-specific subclasses — one class per business role; can be composed
  using DRF's bitwise operators (| and &).

Usage
─────
    class MyView(APIView):
        permission_classes = [IsAuthenticated, IsOwnerOrManager]

    # or with OR composition
        permission_classes = [IsAuthenticated, IsPharmacist | IsCashier]

Superuser bypass
────────────────
Django's is_superuser flag bypasses all role checks (platform admin).
Tenant-level SUPER_ADMIN role is enforced through IsTenantSuperAdmin.
"""
from rest_framework.permissions import BasePermission

from apps.tenants.models import Membership
from apps.tenants.services import TenantService
from core.tenant_context import TenantContext, set_tenant_context


# ── Base permission classes ───────────────────────────────────────────────────

class IsPlatformSuperAdmin(BasePermission):
    """Allows only platform super admins to access platform management endpoints."""
    message = "Only platform super admins can access this endpoint."

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class TenantMembershipPermission(BasePermission):
    """
    Requires a valid X-Tenant-ID header and an active Membership.
    Sets the TenantContext for the duration of the request.
    """
    message = "A valid X-Tenant-ID header and active tenant membership are required."

    def has_permission(self, request, view) -> bool:
        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is None:
            return False

        if request.user.is_superuser:
            set_tenant_context(
                TenantContext(
                    tenant_id=tenant_id,
                    user_id=request.user.id,
                    is_super_admin=True,
                )
            )
            return True

        if not TenantService.has_access(request.user, tenant_id):
            return False

        set_tenant_context(TenantContext(tenant_id=tenant_id, user_id=request.user.id))
        return True


class TenantRolePermission(BasePermission):
    """
    Extends TenantMembershipPermission by enforcing a specific set of roles.
    Subclass and set `required_roles` to a tuple of Membership.Role values.
    """
    required_roles: tuple[str, ...] = ()
    message = "You do not have the required role to perform this action."

    def has_permission(self, request, view) -> bool:
        if request.user.is_superuser:
            # Platform superusers bypass all role checks
            return True
        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is None:
            return False
        return TenantService.has_role(request.user, tenant_id, self.required_roles)


# ── Role-specific permission classes ──────────────────────────────────────────

class IsOwner(TenantRolePermission):
    """Grants access to users with the Owner role."""
    required_roles = (Membership.Role.OWNER,)
    message = "Only Owners can perform this action."


class IsManager(TenantRolePermission):
    """Grants access to users with the Manager role."""
    required_roles = (Membership.Role.MANAGER,)
    message = "Only Managers can perform this action."


class IsCashier(TenantRolePermission):
    """Grants access to users with the Cashier role."""
    required_roles = (Membership.Role.CASHIER,)
    message = "Only Cashiers can perform this action."


class IsInventoryManager(TenantRolePermission):
    """Grants access to users with the Inventory Manager role."""
    required_roles = (Membership.Role.INVENTORY_MANAGER,)
    message = "Only Inventory Managers can perform this action."


class IsPharmacist(TenantRolePermission):
    """Grants access to users with the Pharmacist role."""
    required_roles = (Membership.Role.PHARMACIST,)
    message = "Only Pharmacists can perform this action."


class IsAccountant(TenantRolePermission):
    """Grants access to users with the Accountant role."""
    required_roles = (Membership.Role.ACCOUNTANT,)
    message = "Only Accountants can perform this action."


class IsTenantSuperAdmin(TenantRolePermission):
    """Grants access to users with the Tenant Super Admin role."""
    required_roles = (Membership.Role.SUPER_ADMIN,)
    message = "Only Tenant Super Admins can perform this action."


# ── Convenience composite permissions ─────────────────────────────────────────

class IsOwnerOrManager(TenantRolePermission):
    """Owner OR Manager — general management tasks."""
    required_roles = (Membership.Role.OWNER, Membership.Role.MANAGER)
    message = "Only Owners or Managers can perform this action."


class IsOwnerOrSuperAdmin(TenantRolePermission):
    """Owner OR Tenant Super Admin — elevated administration."""
    required_roles = (Membership.Role.OWNER, Membership.Role.SUPER_ADMIN)
    message = "Only Owners or Super Admins can perform this action."


class CanManageInventory(TenantRolePermission):
    """Roles that can create/update inventory records."""
    required_roles = (
        Membership.Role.OWNER,
        Membership.Role.MANAGER,
        Membership.Role.INVENTORY_MANAGER,
    )
    message = "Only Owners, Managers, or Inventory Managers can manage inventory."


class CanDispense(TenantRolePermission):
    """Roles that can dispense medication (process prescriptions)."""
    required_roles = (
        Membership.Role.OWNER,
        Membership.Role.MANAGER,
        Membership.Role.PHARMACIST,
    )
    message = "Only Owners, Managers, or Pharmacists can dispense medication."


class CanProcessSale(TenantRolePermission):
    """Roles that can record / finalise a sale."""
    required_roles = (
        Membership.Role.OWNER,
        Membership.Role.MANAGER,
        Membership.Role.CASHIER,
        Membership.Role.PHARMACIST,
    )
    message = "Only Owners, Managers, Cashiers, or Pharmacists can process sales."


class CanAccessSales(TenantRolePermission):
    """Roles that can view and operate sales data."""
    required_roles = (
        Membership.Role.OWNER,
        Membership.Role.MANAGER,
        Membership.Role.CASHIER,
    )
    message = "Only Owners, Managers, or Cashiers can access sales data."


class CanAccessPurchases(TenantRolePermission):
    """Roles that can view and manage purchasing data."""
    required_roles = (
        Membership.Role.OWNER,
        Membership.Role.MANAGER,
        Membership.Role.ACCOUNTANT,
    )
    message = "Only Owners, Managers, or Accountants can access purchasing data."


class CanViewFinancials(TenantRolePermission):
    """Roles that can access financial reports."""
    required_roles = (
        Membership.Role.OWNER,
        Membership.Role.MANAGER,
        Membership.Role.ACCOUNTANT,
    )
    message = "Only Owners, Managers, or Accountants can view financial data."


class IsAnyStaff(TenantRolePermission):
    """Any tenant member — broadest role gate, equivalent to TenantMembership."""
    required_roles = (
        Membership.Role.OWNER,
        Membership.Role.MANAGER,
        Membership.Role.CASHIER,
        Membership.Role.INVENTORY_MANAGER,
        Membership.Role.PHARMACIST,
        Membership.Role.ACCOUNTANT,
        Membership.Role.SUPER_ADMIN,
    )
    message = "Active tenant membership required."


# ── Subscription permissions & feature gates ─────────────────────────────────

class HasActiveSubscription(BasePermission):
    """
    Enforces that the current tenant has an active, non-expired subscription.
    Safe HTTP methods (GET, HEAD, OPTIONS) are allowed if read-only access is desired,
    or write operations are blocked if subscription is expired.
    """
    message = "An active subscription is required to perform this action."

    def has_permission(self, request, view) -> bool:
        if request.user.is_superuser:
            return True

        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is None:
            return True  # Handled by TenantMembershipPermission

        from apps.tenants.models import Tenant
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            return False

        sub = getattr(tenant, "subscription", None)
        if sub is None or sub.is_expired:
            return False

        return True


class RequiresReportsFeature(BasePermission):
    """Requires tenant plan to have `has_reports=True`."""
    message = "The Reports feature is not included in your current subscription plan."

    def has_permission(self, request, view) -> bool:
        if request.user.is_superuser:
            return True
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            return False
        from apps.tenants.models import Tenant
        try:
            tenant = Tenant.objects.get(id=tenant_id)
            sub = getattr(tenant, "subscription", None)
            return sub is not None and not sub.is_expired and sub.plan.has_reports
        except Tenant.DoesNotExist:
            return False


class RequiresSMSFeature(BasePermission):
    """Requires tenant plan to have `has_sms=True`."""
    message = "The SMS feature is not included in your current subscription plan."

    def has_permission(self, request, view) -> bool:
        if request.user.is_superuser:
            return True
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            return False
        from apps.tenants.models import Tenant
        try:
            tenant = Tenant.objects.get(id=tenant_id)
            sub = getattr(tenant, "subscription", None)
            return sub is not None and not sub.is_expired and sub.plan.has_sms
        except Tenant.DoesNotExist:
            return False


class RequiresBackupsFeature(BasePermission):
    """Requires tenant plan to have `has_backups=True`."""
    message = "The Backups feature is not included in your current subscription plan."

    def has_permission(self, request, view) -> bool:
        if request.user.is_superuser:
            return True
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            return False
        from apps.tenants.models import Tenant
        try:
            tenant = Tenant.objects.get(id=tenant_id)
            sub = getattr(tenant, "subscription", None)
            return sub is not None and not sub.is_expired and sub.plan.has_backups
        except Tenant.DoesNotExist:
            return False

