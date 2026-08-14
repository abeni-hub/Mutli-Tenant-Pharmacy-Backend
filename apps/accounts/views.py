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
                first_name="Owner" if invitation.role == "owner" else "User",
            )
        else:
            user.set_password(new_password)
            user.is_active = True
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
