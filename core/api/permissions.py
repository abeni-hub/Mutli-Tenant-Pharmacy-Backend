from rest_framework.permissions import BasePermission

from apps.tenants.services import TenantService
from core.tenant_context import TenantContext, set_tenant_context


class TenantMembershipPermission(BasePermission):
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
        set_tenant_context(TenantContext(tenant_id, request.user.id))
        return True


class TenantRolePermission(BasePermission):
    required_roles: tuple[str, ...] = ()

    def has_permission(self, request, view) -> bool:
        if request.user.is_superuser:
            return True
        tenant_id = getattr(request, "tenant_id", None)
        return tenant_id is not None and TenantService.has_role(
            request.user, tenant_id, self.required_roles
        )
