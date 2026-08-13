from django.db import models

from core.models import UUIDModel


class Tenant(UUIDModel):
    slug = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    registration_number = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Membership(UUIDModel):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        CASHIER = "cashier", "Cashier"
        PHARMACIST = "pharmacist", "Pharmacist"
        SUPER_ADMIN = "super_admin", "Super Admin"

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CASHIER)
    is_active = models.BooleanField(default=True)
    invited_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sent_invitations",
    )
    joined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "user"), name="unique_tenant_user_membership"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} – {self.role} @ {self.tenant}"


class Branch(UUIDModel):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="branches"
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    is_main = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "code"), name="unique_tenant_branch_code"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code}) @ {self.tenant.name}"
