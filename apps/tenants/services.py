from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.utils.text import slugify

from apps.accounts.models import User
from apps.audit.services import AuditService
from apps.tenants.models import Membership, Tenant


@dataclass(frozen=True, slots=True)
class TenantCreateData:
    name: str
    registration_number: str = ""


class TenantService:
    @staticmethod
    @transaction.atomic
    def create_for_owner(owner: User, data: TenantCreateData) -> Tenant:
        base_slug = slugify(data.name)
        slug = base_slug
        suffix = 2
        while Tenant.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        tenant = Tenant.objects.create(
            name=data.name,
            slug=slug,
            registration_number=data.registration_number,
        )
        Membership.objects.create(tenant=tenant, user=owner, role=Membership.Role.OWNER)
        AuditService.record(
            tenant=tenant,
            actor=owner,
            action="create",
            entity_type="tenant",
            entity_id=tenant.id,
            metadata={"name": tenant.name},
        )
        return tenant

    @staticmethod
    def accessible_to(user: User) -> list[Tenant]:
        return list(
            Tenant.objects.filter(
                memberships__user=user, memberships__is_active=True, is_active=True
            ).distinct()
        )

    @staticmethod
    def has_access(user: User, tenant_id: UUID) -> bool:
        if user.is_superuser:
            return Tenant.objects.filter(id=tenant_id, is_active=True).exists()
        return Membership.objects.filter(
            user=user,
            tenant_id=tenant_id,
            tenant__is_active=True,
            is_active=True,
        ).exists()

    @staticmethod
    def has_role(user: User, tenant_id: UUID, roles: tuple[str, ...]) -> bool:
        if user.is_superuser:
            return Tenant.objects.filter(id=tenant_id, is_active=True).exists()
        return Membership.objects.filter(
            user=user,
            tenant_id=tenant_id,
            role__in=roles,
            is_active=True,
            tenant__is_active=True,
        ).exists()
