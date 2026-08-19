"""
Views for the accounts app.

Endpoints:
    POST   /auth/login/               — obtain JWT tokens
    POST   /auth/logout/              — blacklist refresh token
    POST   /auth/token/refresh/       — rotate refresh token (SimpleJWT)
    POST   /auth/password/reset/      — request password reset email
    POST   /auth/password/confirm/    — confirm password reset with token
    GET    /auth/me/                  — current user profile
    PATCH  /auth/me/                  — update current user profile
    GET    /auth/login-history/       — own login history (admins see all)
    POST   /auth/register/            — create a new user account
"""
from __future__ import annotations

import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import LoginHistory
from apps.accounts.serializers import (
    LoginHistorySerializer,
    LoginSerializer,
    LogoutSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegistrationSerializer,
    UserProfileUpdateSerializer,
    UserSerializer,
)
from apps.accounts.services import AuthenticationError, AuthService

logger = logging.getLogger(__name__)


# ── Login ─────────────────────────────────────────────────────────────────────

class LoginView(APIView):
    """
    POST /auth/login/

    Accepts `email` + `password`, enforces brute-force lockout,
    and returns an access + refresh JWT pair along with the user profile.
    """
    permission_classes = (AllowAny,)
    serializer_class = LoginSerializer  # for schema generation

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = AuthService.login(
                email=serializer.validated_data["email"],
                password=serializer.validated_data["password"],
                request=request,
            )
        except AuthenticationError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response(
            {
                "access": result.tokens.access,
                "refresh": result.tokens.refresh,
                "user": UserSerializer(result.user, context={"request": request}).data,
            },
            status=status.HTTP_200_OK,
        )


# ── Logout ────────────────────────────────────────────────────────────────────

class LogoutView(APIView):
    """
    POST /auth/logout/

    Blacklists the provided refresh token so it cannot be used again.
    """
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            AuthService.logout(serializer.validated_data["refresh"])
        except AuthenticationError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"detail": "Successfully logged out."}, status=status.HTTP_200_OK)


# ── Password reset ────────────────────────────────────────────────────────────

class PasswordResetRequestView(APIView):
    """
    POST /auth/password/reset/

    Sends a password reset email if the address is registered.
    Always returns 200 to prevent user enumeration.
    """
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        AuthService.request_password_reset(serializer.validated_data["email"])
        return Response(
            {"detail": "If that email address is registered, you will receive a reset link shortly."},
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    """
    POST /auth/password/confirm/

    Validates the reset token and sets the new password.
    """
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            AuthService.confirm_password_reset(
                token_value=str(serializer.validated_data["token"]),
                new_password=serializer.validated_data["new_password"],
            )
        except AuthenticationError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"detail": "Password has been reset successfully."},
            status=status.HTTP_200_OK,
        )


class PasswordChangeView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        from apps.accounts.serializers import PasswordChangeSerializer
        from apps.audit.services import AuditService

        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        current_password = serializer.validated_data.get("current_password", "")
        new_password = serializer.validated_data["new_password"]

        if user.must_change_password or (current_password and user.check_password(current_password)):
            user.set_password(new_password)
            user.must_change_password = False
            user.save(update_fields=["password", "must_change_password"])

            AuditService.record(
                tenant=None,
                actor=user,
                action="update",
                entity_type="accounts.User",
                entity_id=user.id,
                metadata={"action": "password_changed", "must_change_password": False},
            )

            return Response(
                {
                    "message": "Password changed successfully.",
                    "user": UserSerializer(user, context={"request": request}).data,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {"detail": "Invalid current password."},
            status=status.HTTP_400_BAD_REQUEST,
        )


# ── Profile (me) ──────────────────────────────────────────────────────────────

class MeViewSet(viewsets.GenericViewSet):
    """
    GET  /auth/me/   — retrieve own profile (including current tenant role)
    PATCH /auth/me/  — update first_name, last_name, phone_number
    """
    permission_classes = (IsAuthenticated,)

    def get_serializer_class(self):
        if self.action == "update_profile":
            return UserProfileUpdateSerializer
        return UserSerializer

    def list(self, request: Request) -> Response:
        serializer = UserSerializer(request.user, context={"request": request})
        return Response(serializer.data)

    @action(detail=False, methods=["patch"], url_path="profile")
    def update_profile(self, request: Request) -> Response:
        serializer = UserProfileUpdateSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user, context={"request": request}).data)


# ── Registration ──────────────────────────────────────────────────────────────

class RegistrationViewSet(viewsets.GenericViewSet):
    """
    POST /auth/register/  — create a new user account (no tenant context required)
    """
    permission_classes = (AllowAny,)
    serializer_class = RegistrationSerializer

    def create(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            UserSerializer(user, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


# ── Login history ─────────────────────────────────────────────────────────────

class LoginHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /auth/login-history/       — list login attempts
    GET /auth/login-history/{id}/  — retrieve a single record

    Regular users see only their own history.
    Superusers see all history (filterable by user).
    """
    permission_classes = (IsAuthenticated,)
    serializer_class = LoginHistorySerializer
    filterset_fields = ("success",)
    search_fields = ("email_attempted", "ip_address")
    ordering_fields = ("login_at",)
    def get_queryset(self):
        user = self.request.user
        qs = LoginHistory.objects.select_related("user", "tenant")
        if user.is_superuser:
            return qs
        return qs.filter(user=user)


# ── Password Setup / Invitation Activation ──────────────────────────────────

class SetupPasswordView(APIView):
    """
    POST /auth/setup-password/

    Validates one-time invitation/password-setup token, sets user's password using Django hash,
    activates account, and accepts the invitation.
    """
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        token_str = request.data.get("token")
        new_password = request.data.get("new_password") or request.data.get("password")

        if not token_str or not new_password:
            return Response(
                {"detail": "Both token and new_password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(new_password) < 8:
            return Response(
                {"detail": "Password must be at least 8 characters long."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.utils import timezone
        from apps.tenants.models import UserInvitation, Membership, Tenant
        from apps.accounts.models import User
        from apps.audit.services import AuditService

        invitation = UserInvitation.objects.filter(token=token_str).first()
        if not invitation:
            return Response(
                {"detail": "Invalid or expired setup token."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if invitation.status == UserInvitation.Status.ACCEPTED:
            return Response(
                {"detail": "This setup token has already been used."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if invitation.expires_at and invitation.expires_at < timezone.now():
            invitation.status = UserInvitation.Status.EXPIRED
            invitation.save(update_fields=["status"])
            return Response(
                {"detail": "This setup token has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get or create user
        email = invitation.email.lower().strip()
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            user = User.objects.create_user(
                email=email,
                password=new_password,
                first_name="Super" if invitation.role == "super_admin" else ("Owner" if invitation.role == "owner" else "User"),
                last_name="Admin" if invitation.role == "super_admin" else "",
            )
        else:
            user.set_password(new_password)

        user.is_active = True
        user.must_change_password = False
        if invitation.role == "super_admin" or invitation.role == Membership.Role.SUPER_ADMIN:
            user.is_superuser = True
            user.is_staff = True
        user.save()

        # Update membership if tenant is assigned
        if invitation.tenant:
            Membership.objects.update_or_create(
                tenant=invitation.tenant,
                user=user,
                defaults={"role": invitation.role, "is_active": True},
            )

        invitation.status = UserInvitation.Status.ACCEPTED
        invitation.save(update_fields=["status"])

        AuditService.record(
            tenant=invitation.tenant,
            actor=user,
            action="update",
            entity_type="accounts.User",
            entity_id=user.id,
            metadata={"email": user.email, "setup_completed": True},
        )

        return Response(
            {"detail": "Password successfully set. Your account is now active."},
            status=status.HTTP_200_OK,
        )


class PermissionCatalogViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (IsAuthenticated,)

    def list(self, request: Request) -> Response:
        from apps.accounts.models import PermissionCategory, Permission
        from apps.accounts.serializers import PermissionCategorySerializer
        from django.db.models import Prefetch

        user = request.user
        if not user.is_superuser:
            categories = PermissionCategory.objects.prefetch_related(
                Prefetch(
                    "permissions",
                    queryset=Permission.objects.filter(scope=Permission.Scope.TENANT).order_by("key"),
                )
            ).all()
        else:
            categories = PermissionCategory.objects.prefetch_related("permissions").all()

        serialized = PermissionCategorySerializer(categories, many=True).data
        if not user.is_superuser:
            serialized = [cat for cat in serialized if cat.get("permissions") and len(cat["permissions"]) > 0]

        return Response(serialized)


class TenantRoleViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)

    def get_serializer_class(self):
        from apps.accounts.serializers import RoleSerializer
        return RoleSerializer

    def get_queryset(self):
        from apps.accounts.models import Role
        from django.db.models import Q

        user = self.request.user
        tenant_id = getattr(self.request, "tenant_id", None)
        if not tenant_id and "tenant_id" in self.request.query_params:
            tenant_id = self.request.query_params.get("tenant_id")

        if user.is_superuser and not tenant_id:
            return Role.objects.filter(scope=Role.Scope.GLOBAL).prefetch_related("permissions")

        if tenant_id:
            return Role.objects.filter(
                scope=Role.Scope.TENANT
            ).filter(
                Q(is_system=True) | Q(tenant_id=tenant_id)
            ).prefetch_related("permissions")

        return Role.objects.filter(scope=Role.Scope.TENANT, is_system=True).prefetch_related("permissions")

    def _validate_permission_keys(self, perm_keys, is_super):
        from apps.accounts.models import Permission
        from rest_framework.exceptions import PermissionDenied

        if not perm_keys:
            return []

        perms = Permission.objects.filter(key__in=perm_keys)
        if len(perms) != len(set(perm_keys)):
            raise PermissionDenied("One or more invalid permission keys submitted.")

        if not is_super:
            global_perms = [p.key for p in perms if p.scope == Permission.Scope.GLOBAL]
            if global_perms:
                raise PermissionDenied(
                    f"Permission Denied: Cannot assign GLOBAL scope permissions ({', '.join(global_perms)}) to a tenant role."
                )
        return perms

    def create(self, request: Request) -> Response:
        import uuid
        from apps.accounts.models import Role
        from apps.accounts.serializers import RoleCreateUpdateSerializer, RoleSerializer
        from apps.audit.services import AuditService
        from rest_framework.exceptions import ValidationError, PermissionDenied

        serializer = RoleCreateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        name = serializer.validated_data["name"].strip()
        description = serializer.validated_data.get("description", "")
        perm_keys = serializer.validated_data.get("permission_keys", [])

        tenant_id = getattr(request, "tenant_id", None)
        is_super = request.user.is_superuser

        if not is_super:
            scope = Role.Scope.TENANT
            if not tenant_id:
                raise ValidationError("Tenant context required to create a custom role.")
        else:
            scope = serializer.validated_data.get("scope", Role.Scope.GLOBAL)

        perms = self._validate_permission_keys(perm_keys, is_super)

        role_key = f"{name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}"

        role = Role.objects.create(
            key=role_key,
            name=name,
            description=description,
            scope=scope,
            tenant_id=tenant_id if scope == Role.Scope.TENANT else None,
            is_system=False,
        )

        role.permissions.set(perms)

        AuditService.record(
            tenant=role.tenant,
            actor=request.user,
            action="create",
            entity_type="accounts.Role",
            entity_id=role.id,
            metadata={"role_name": role.name, "permission_count": len(perms)},
        )
        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args, **kwargs) -> Response:
        return self._perform_update(request, partial=False, *args, **kwargs)

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        return self._perform_update(request, partial=True, *args, **kwargs)

    def _perform_update(self, request: Request, partial: bool, *args, **kwargs) -> Response:
        from apps.accounts.serializers import RoleCreateUpdateSerializer, RoleSerializer
        from apps.audit.services import AuditService
        from rest_framework.exceptions import PermissionDenied, ValidationError

        role = self.get_object()
        is_super = request.user.is_superuser
        tenant_id = getattr(request, "tenant_id", None)

        if not is_super:
            if role.is_system or role.scope == Role.Scope.GLOBAL or str(role.tenant_id) != str(tenant_id):
                raise PermissionDenied("Permission Denied: Cannot modify global, protected system, or foreign tenant roles.")

        serializer = RoleCreateUpdateSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        if "name" in serializer.validated_data:
            role.name = serializer.validated_data["name"].strip()
        if "description" in serializer.validated_data:
            role.description = serializer.validated_data["description"].strip()

        if "permission_keys" in serializer.validated_data:
            perm_keys = serializer.validated_data["permission_keys"]
            perms = self._validate_permission_keys(perm_keys, is_super)
            role.permissions.set(perms)

        role.save()

        AuditService.record(
            tenant=role.tenant,
            actor=request.user,
            action="update",
            entity_type="accounts.Role",
            entity_id=role.id,
            metadata={"role_name": role.name},
        )
        return Response(RoleSerializer(role).data, status=status.HTTP_200_OK)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        from apps.audit.services import AuditService
        from rest_framework.exceptions import PermissionDenied, ValidationError

        role = self.get_object()
        is_super = request.user.is_superuser
        tenant_id = getattr(request, "tenant_id", None)

        if role.is_system:
            raise ValidationError("System roles are protected and cannot be deleted.")

        if not is_super:
            if role.scope == Role.Scope.GLOBAL or str(role.tenant_id) != str(tenant_id):
                raise PermissionDenied("Permission Denied: Cannot delete global or foreign tenant roles.")

        AuditService.record(
            tenant=role.tenant,
            actor=request.user,
            action="delete",
            entity_type="accounts.Role",
            entity_id=role.id,
            metadata={"role_name": role.name},
        )
        role.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
