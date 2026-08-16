import uuid
from datetime import timedelta

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager["User"]):
    def create_user(
        self, email: str, password: str | None = None, **extra_fields
    ) -> "User":
        if not email:
            raise ValueError("Users must have an email address.")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, primary_key=True
    )
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    # Security fields
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    must_change_password = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ("email",)

    def __str__(self) -> str:
        return self.email

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def is_locked_out(self) -> bool:
        """Return True if the account is currently locked due to failed attempts."""
        if self.locked_until is None:
            return False
        return timezone.now() < self.locked_until

    def record_failed_login(self, max_attempts: int = 5, lockout_minutes: int = 15) -> None:
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= max_attempts:
            self.locked_until = timezone.now() + timedelta(minutes=lockout_minutes)
        self.save(update_fields=["failed_login_attempts", "locked_until"])

    def reset_failed_logins(self) -> None:
        self.failed_login_attempts = 0
        self.locked_until = None
        self.save(update_fields=["failed_login_attempts", "locked_until"])


class PasswordResetToken(models.Model):
    """Single-use token for password reset requests."""

    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="password_reset_tokens"
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"PasswordResetToken({self.user}, used={self.is_used})"

    def is_valid(self) -> bool:
        return not self.is_used and timezone.now() < self.expires_at

    @classmethod
    def create_for_user(cls, user: "User", expiry_minutes: int = 60) -> "PasswordResetToken":
        # Invalidate any existing unused tokens for this user
        cls.objects.filter(user=user, is_used=False).update(is_used=True)
        return cls.objects.create(
            user=user,
            expires_at=timezone.now() + timedelta(minutes=expiry_minutes),
        )


class LoginHistory(models.Model):
    """Audit log for all login attempts (successful and failed)."""

    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="login_history",
    )
    email_attempted = models.EmailField(blank=True)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="login_history",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    success = models.BooleanField(default=False)
    failure_reason = models.CharField(max_length=200, blank=True)
    login_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-login_at",)
        indexes = [
            models.Index(fields=("user", "login_at")),
            models.Index(fields=("ip_address", "login_at")),
        ]

    def __str__(self) -> str:
        status = "success" if self.success else "failed"
        return f"Login({self.email_attempted}, {status}, {self.login_at})"


class PermissionCategory(models.Model):
    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "name")
        verbose_name_plural = "Permission categories"

    def __str__(self) -> str:
        return self.name


class Permission(models.Model):
    class Scope(models.TextChoices):
        GLOBAL = "global", "Global"
        TENANT = "tenant", "Tenant"

    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    category = models.ForeignKey(
        PermissionCategory, on_delete=models.CASCADE, related_name="permissions"
    )
    scope = models.CharField(max_length=20, choices=Scope.choices, default=Scope.GLOBAL)
    is_system = models.BooleanField(default=False)

    class Meta:
        ordering = ("category__order", "key")

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"


class Role(models.Model):
    class Scope(models.TextChoices):
        GLOBAL = "global", "Global"
        TENANT = "tenant", "Tenant"

    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    scope = models.CharField(max_length=20, choices=Scope.choices, default=Scope.GLOBAL)
    tenant = models.ForeignKey(
        "tenants.Tenant", null=True, blank=True, on_delete=models.CASCADE, related_name="custom_roles"
    )
    is_system = models.BooleanField(default=False)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.scope})"


class UserRole(models.Model):
    id = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="user_assignments")
    tenant = models.ForeignKey(
        "tenants.Tenant", null=True, blank=True, on_delete=models.CASCADE, related_name="user_role_assignments"
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_user_roles"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "role", "tenant"), name="unique_user_role_tenant"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user.email} -> {self.role.name} @ {self.tenant or 'Global'}"

