from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.tenants.models import Membership, Tenant
from apps.tenants.services import TenantCreateData, TenantService


class Command(BaseCommand):
    help = "Create the demo tenant and seeded staff accounts expected by the UI and tests."

    def handle(self, *args, **options):
        password = "SecurePassword123!"
        tenant_name = "Abeni Pharmacy"
        tenant_slug = "abeni-pharmacy"

        tenant, _ = Tenant.objects.get_or_create(
            slug=tenant_slug,
            defaults={"name": tenant_name, "registration_number": "ABC-001"},
        )
        if not tenant.name:
            tenant.name = tenant_name
            tenant.registration_number = "ABC-001"
            tenant.save(update_fields=["name", "registration_number"])

        account_specs = [
            ("owner@abeni.test", "Owner", "User", Membership.Role.OWNER),
            ("cashier@abeni.test", "Cashier", "User", Membership.Role.CASHIER),
            ("pharmacist@abeni.test", "Pharmacist", "User", Membership.Role.PHARMACIST),
            ("superadmin@abeni.test", "Super", "Admin", Membership.Role.SUPER_ADMIN),
        ]

        for email, first_name, last_name, role in account_specs:
            is_super = (email == "superadmin@abeni.test")
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "is_superuser": is_super,
                    "is_staff": is_super,
                },
            )
            update_fields = []
            if user.first_name != first_name:
                user.first_name = first_name
                update_fields.append("first_name")
            if user.last_name != last_name:
                user.last_name = last_name
                update_fields.append("last_name")
            user.failed_login_attempts = 0
            user.locked_until = None
            user.is_active = True
            if is_super:
                user.is_superuser = True
                user.is_staff = True
            if not user.check_password(password):
                user.set_password(password)

            user.save()

            if not is_super:
                Membership.objects.update_or_create(
                    tenant=tenant,
                    user=user,
                    defaults={"role": role, "is_active": True},
                )

        self.stdout.write(self.style.SUCCESS("Seeded demo tenant and accounts."))
