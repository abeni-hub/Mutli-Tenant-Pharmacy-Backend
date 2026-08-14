from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import User
from apps.audit.services import AuditService
from apps.subscriptions.models import SubscriptionPlan, TenantSubscription
from apps.tenants.models import Branch, Membership, Tenant


@dataclass(frozen=True, slots=True)
class TenantCreateData:
    name: str
    registration_number: str = ""
    owner_first_name: str = ""
    owner_last_name: str = ""
    owner_email: str = ""
    owner_phone: str = ""
    plan_code: str = "enterprise"
    branch_name: str = ""
    branch_code: str = ""
    address: str = ""
    phone: str = ""


class TenantService:
    @staticmethod
    @transaction.atomic
    def create_for_owner(owner: User, data: TenantCreateData) -> Tenant:
        return TenantService.create_for_super_admin(
            created_by=owner,
            data=data,
            owner=owner,
        )

    @staticmethod
    @transaction.atomic
    def create_for_super_admin(
        *,
        created_by: User,
        data: TenantCreateData,
        owner: User | None = None,
    ) -> Tenant:
        base_slug = slugify(data.name) or "tenant"
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

        owner_user = owner
        if owner_user is None and data.owner_email.strip():
            email = data.owner_email.strip().lower()
            owner_user = User.objects.filter(email__iexact=email).first()
            if owner_user is None:
                owner_user = User.objects.create_user(
                    email=email,
                    password="SecurePassword123!",
                    first_name=data.owner_first_name or "Owner",
                    last_name=data.owner_last_name or "",
                    phone_number=data.owner_phone or data.phone,
                )

        if owner_user is not None:
            Membership.objects.get_or_create(
                tenant=tenant,
                user=owner_user,
                defaults={"role": Membership.Role.OWNER, "is_active": True},
            )

        # Create Subscription
        plan = SubscriptionPlan.objects.filter(code__iexact=data.plan_code).first()
        if plan is None:
            plan = SubscriptionPlan.objects.filter(is_active=True).first()
        if plan is None:
            plan = SubscriptionPlan.objects.create(
                name="Enterprise Plan",
                code="enterprise",
                price_monthly=199,
                price_yearly=1990,
                max_branches=-1,
                max_users=-1,
                max_medicines=-1,
            )

        now = timezone.now()
        TenantSubscription.objects.update_or_create(
            tenant=tenant,
            defaults={
                "plan": plan,
                "status": TenantSubscription.Status.ACTIVE,
                "billing_cycle": TenantSubscription.BillingCycle.YEARLY,
                "starts_at": now,
                "expires_at": now + timezone.timedelta(days=365),
            },
        )

        # Create Initial Main Branch
        main_branch_name = data.branch_name.strip() or f"{data.name} Main Branch"
        clean_code = (data.branch_code.strip() or f"{slug[:10].upper()}-MAIN").replace(" ", "-")
        code_suffix = 2
        unique_code = clean_code
        while Branch.objects.filter(tenant=tenant, code=unique_code).exists():
            unique_code = f"{clean_code}-{code_suffix}"
            code_suffix += 1

        Branch.objects.create(
            tenant=tenant,
            name=main_branch_name,
            code=unique_code,
            address=data.address,
            phone=data.phone or data.owner_phone,
            is_main=True,
            is_active=True,
        )

        AuditService.record(
            tenant=tenant,
            actor=created_by,
            action="create",
            entity_type="tenants.Tenant",
            entity_id=tenant.id,
            metadata={
                "name": tenant.name,
                "owner_email": owner_user.email if owner_user else "",
                "plan": plan.name,
            },
        )
        return tenant

    @staticmethod
    def accessible_to(user: User) -> list[Tenant]:
        if user.is_superuser:
            return list(Tenant.objects.filter(is_active=True).distinct())
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
