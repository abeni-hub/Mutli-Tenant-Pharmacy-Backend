from io import StringIO

from django.core.management import call_command

from apps.accounts.models import User
from apps.tenants.models import Membership, Tenant


def test_seed_demo_users_creates_expected_roles(db):
    call_command("seed_demo_users", stdout=StringIO(), stderr=StringIO())

    tenant = Tenant.objects.get(slug="abeni-pharmacy")
    expected_roles = {
        "owner@abeni.test": Membership.Role.OWNER,
        "manager@abeni.test": Membership.Role.MANAGER,
        "cashier@abeni.test": Membership.Role.CASHIER,
        "inventory@abeni.test": Membership.Role.INVENTORY_MANAGER,
        "pharmacist@abeni.test": Membership.Role.PHARMACIST,
        "accountant@abeni.test": Membership.Role.ACCOUNTANT,
        "superadmin@abeni.test": Membership.Role.SUPER_ADMIN,
    }

    for email, role in expected_roles.items():
        user = User.objects.get(email=email)
        membership = Membership.objects.get(tenant=tenant, user=user)
        assert membership.role == role
        assert user.check_password("SecurePassword123!")
