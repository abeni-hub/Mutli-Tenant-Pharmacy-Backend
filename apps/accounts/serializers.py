"""
Serializers for the accounts app.

Covers: user profile, login, logout, token refresh,
password reset request/confirm, and login history.
"""
from __future__ import annotations

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.accounts.models import LoginHistory, User


# ── User profile ─────────────────────────────────────────────────────────────

class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    role = serializers.SerializerMethodField(
        help_text="Role within the current tenant (from X-Tenant-ID header)"
    )

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "phone_number",
            "is_active",
            "is_superuser",
            "is_staff",
            "date_joined",
            "last_login_ip",
            "role",
        )
        read_only_fields = ("id", "email", "is_active", "is_superuser", "is_staff", "date_joined", "last_login_ip")

    def get_role(self, obj: User) -> str | None:
        """Return the user's role in the current tenant, or primary role fallback."""
        from apps.tenants.models import Membership

        if obj.is_superuser or obj.memberships.filter(role=Membership.Role.SUPER_ADMIN, is_active=True).exists():
            return "super_admin"

        request = self.context.get("request")
        tenant_id = getattr(request, "tenant_id", None) if request else None

        if tenant_id is not None:
            membership = obj.memberships.filter(tenant_id=tenant_id, is_active=True).first()
            return membership.role if membership else None

        # Fallback when X-Tenant-ID is not provided (e.g. login endpoint response before tenant selection)
        primary_membership = obj.memberships.filter(is_active=True).first()
        return primary_membership.role if primary_membership else None



class UserProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "phone_number")

    def update(self, instance: User, validated_data: dict) -> User:
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save(update_fields=list(validated_data.keys()))
        return instance


# ── Authentication ────────────────────────────────────────────────────────────

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class LoginResponseSerializer(serializers.Serializer):
    """Shape of a successful login response (documentation / OpenAPI)."""
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserSerializer()


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(
        help_text="The refresh token to blacklist."
    )


class TokenRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


# ── Password reset ────────────────────────────────────────────────────────────

class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.UUIDField()
    new_password = serializers.CharField(
        write_only=True,
        min_length=12,
        style={"input_type": "password"},
    )
    confirm_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )

    def validate(self, attrs: dict) -> dict:
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )
        # Run Django's password validators
        try:
            validate_password(attrs["new_password"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from exc
        return attrs


# ── SimpleJWT customisation ───────────────────────────────────────────────────

class PharmacyTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extends the default SimpleJWT serializer so the token contains
    extra claims (email, is_superuser).

    NOTE: This serializer is referenced in SIMPLE_JWT['TOKEN_OBTAIN_SERIALIZER']
    so SimpleJWT uses it automatically.
    """

    @classmethod
    def get_token(cls, user: User):  # type: ignore[override]
        token = super().get_token(user)
        # Extra claims embedded in the JWT payload
        token["email"] = user.email
        token["is_superuser"] = user.is_superuser
        return token


# ── Registration ──────────────────────────────────────────────────────────────

class RegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True, min_length=12, style={"input_type": "password"}
    )
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    phone_number = serializers.CharField(max_length=20, required=False, default="")

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def validate_password(self, value: str) -> str:
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def create(self, validated_data: dict) -> User:
        return User.objects.create_user(**validated_data)


class LoginHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LoginHistory
        fields = (
            "id",
            "email_attempted",
            "ip_address",
            "user_agent",
            "success",
            "failure_reason",
            "login_at",
        )
        read_only_fields = fields


# ── RBAC Serializers ──────────────────────────────────────────────────────────

from apps.accounts.models import Permission, PermissionCategory, Role, UserRole


class PermissionSerializer(serializers.ModelSerializer):
    category_key = serializers.CharField(source="category.key", read_only=True)

    class Meta:
        model = Permission
        fields = ("id", "key", "name", "description", "category_key", "scope", "is_system")


class PermissionCategorySerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)

    class Meta:
        model = PermissionCategory
        fields = ("id", "key", "name", "description", "order", "permissions")


class RoleSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)
    permission_keys = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = (
            "id",
            "key",
            "name",
            "description",
            "scope",
            "tenant",
            "is_system",
            "permissions",
            "permission_keys",
            "created_at",
            "updated_at",
        )

    def get_permission_keys(self, obj: Role) -> list[str]:
        return list(obj.permissions.values_list("key", flat=True))


class RoleCreateUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    scope = serializers.ChoiceField(choices=Role.Scope.choices, default=Role.Scope.GLOBAL)
    permission_keys = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )

