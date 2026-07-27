from rest_framework import serializers

from apps.tenants.models import Membership, Tenant


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = (
            "id",
            "name",
            "slug",
            "registration_number",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "slug", "is_active", "created_at")


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
