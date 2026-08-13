from io import StringIO

from django.core.management import call_command

from apps.accounts.models import User
from apps.tenants.models import Membership, Tenant


def test_seed_demo_users_creates_expected_roles(db):
    call_command("seed_demo_users", stdout=StringIO(), stderr=StringIO())

    tenant = Tenant.objects.get(slug="abeni-pharmacy")
    expected_tenant_roles = {
        "owner@abeni.test": Membership.Role.OWNER,
        "cashier@abeni.test": Membership.Role.CASHIER,
        "pharmacist@abeni.test": Membership.Role.PHARMACIST,
    }

    for email, role in expected_tenant_roles.items():
        user = User.objects.get(email=email)
        membership = Membership.objects.get(tenant=tenant, user=user)
        assert membership.role == role
        assert user.check_password("SecurePassword123!")

    sa_user = User.objects.get(email="superadmin@abeni.test")
    assert sa_user.is_superuser is True
    assert sa_user.check_password("SecurePassword123!")
