from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import LoginHistory, PasswordResetToken, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "email", "first_name", "last_name", "phone_number",
        "is_active", "is_staff", "is_superuser",
        "failed_login_attempts", "locked_until", "date_joined",
    )
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("email", "first_name", "last_name", "phone_number")
    ordering = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "phone_number")}),
        (
            "Security",
            {
                "fields": (
                    "failed_login_attempts",
                    "locked_until",
                    "last_login_ip",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Dates", {"fields": ("date_joined",)}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email", "password1", "password2",
                    "first_name", "last_name", "phone_number",
                ),
            },
        ),
    )
    readonly_fields = ("date_joined", "last_login_ip")


@admin.register(LoginHistory)
class LoginHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "email_attempted", "user", "ip_address",
        "success", "failure_reason", "login_at",
    )
    list_filter = ("success",)
    search_fields = ("email_attempted", "ip_address", "user__email")
    ordering = ("-login_at",)
    readonly_fields = (
        "user", "email_attempted", "tenant", "ip_address",
        "user_agent", "success", "failure_reason", "login_at",
    )

    def has_add_permission(self, request):
        return False  # Audit log — read-only in admin

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "token", "expires_at", "is_used", "created_at")
    list_filter = ("is_used",)
    search_fields = ("user__email",)
    ordering = ("-created_at",)
    readonly_fields = ("token", "user", "expires_at", "created_at")
