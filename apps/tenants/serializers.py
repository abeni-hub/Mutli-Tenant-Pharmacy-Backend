from rest_framework import serializers

from apps.tenants.models import Branch, FeatureFlag, Membership, Tenant, UserInvitation


class TenantSerializer(serializers.ModelSerializer):
    owner_email = serializers.SerializerMethodField()
    branch_count = serializers.SerializerMethodField()
    subscription_status = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = (
            "id",
            "name",
            "slug",
            "registration_number",
            "is_active",
            "created_at",
            "owner_email",
            "branch_count",
            "subscription_status",
        )
        read_only_fields = ("id", "slug", "is_active", "created_at", "owner_email", "branch_count", "subscription_status")

    def get_owner_email(self, obj: Tenant) -> str:
        owner_membership = obj.memberships.filter(role=Membership.Role.OWNER, is_active=True).select_related("user").first()
        return owner_membership.user.email if owner_membership else ""

    def get_branch_count(self, obj: Tenant) -> int:
        return obj.branches.filter(is_active=True).count()

    def get_subscription_status(self, obj: Tenant) -> str:
        sub = getattr(obj, "subscription", None)
        return sub.status if sub else "active"


class TenantCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    registration_number = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )


class MembershipSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(source="user.full_name", read_only=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = Membership
        fields = (
            "id",
            "user",
            "user_email",
            "user_full_name",
            "role",
            "role_display",
            "is_active",
            "joined_at",
        )
        read_only_fields = ("id", "user_email", "user_full_name", "role_display", "joined_at")


class BranchSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)

    class Meta:
        model = Branch
        fields = (
            "id",
            "tenant",
            "tenant_name",
            "name",
            "code",
            "address",
            "phone",
            "is_main",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "tenant_name", "created_at", "updated_at")


class BranchCreateSerializer(serializers.Serializer):
    tenant_id = serializers.UUIDField()
    name = serializers.CharField(max_length=200)
    code = serializers.CharField(max_length=50)
    address = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    is_main = serializers.BooleanField(required=False, default=False)


class FeatureFlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureFlag
        fields = ("id", "key", "name", "description", "module", "is_enabled", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class UserInvitationSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.name", read_only=True, default="")
    invited_by_email = serializers.CharField(source="invited_by.email", read_only=True)

    class Meta:
        model = UserInvitation
        fields = (
            "id",
            "email",
            "tenant",
            "tenant_name",
            "role",
            "token",
            "status",
            "invited_by_email",
            "expires_at",
            "created_at",
        )
        read_only_fields = ("id", "token", "tenant_name", "invited_by_email", "created_at")


class UserInviteCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=Membership.Role.choices, default=Membership.Role.PHARMACIST)
    tenant_id = serializers.UUIDField(required=False, allow_null=True)
