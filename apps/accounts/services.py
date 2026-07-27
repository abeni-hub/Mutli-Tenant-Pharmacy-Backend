"""
Authentication service layer.

Handles all auth business logic: login, logout, token refresh,
password reset, and login history recording.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import LoginHistory, PasswordResetToken, User

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TokenPair:
    access: str
    refresh: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    user: User
    tokens: TokenPair


class AuthService:
    """Central service for authentication operations."""

    # ── Login ────────────────────────────────────────────────────────────────

    @staticmethod
    def login(
        *,
        email: str,
        password: str,
        request: "HttpRequest | None" = None,
    ) -> LoginResult:
        """
        Validate credentials, enforce brute-force protection, and return tokens.

        Raises:
            AuthenticationError: on any failure (generic message to prevent enumeration)
        """
        ip = AuthService._get_ip(request)
        user_agent = AuthService._get_user_agent(request)

        # Attempt to find user first (for lockout check)
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Record failed attempt with no user reference
            AuthService._record_login(
                user=None,
                email_attempted=email,
                ip=ip,
                user_agent=user_agent,
                success=False,
                failure_reason="user_not_found",
            )
            raise AuthenticationError("Invalid email or password.")

        # Check lockout before attempting password verification
        if user.is_locked_out():
            AuthService._record_login(
                user=user,
                email_attempted=email,
                ip=ip,
                user_agent=user_agent,
                success=False,
                failure_reason="account_locked",
            )
            raise AuthenticationError(
                "Account temporarily locked due to too many failed attempts. "
                "Please try again later."
            )

        # Verify password via Django's authenticate
        authenticated = authenticate(request, username=email, password=password)
        if authenticated is None:
            max_attempts = getattr(settings, "MAX_LOGIN_ATTEMPTS", 5)
            lockout_minutes = getattr(settings, "ACCOUNT_LOCKOUT_MINUTES", 15)
            user.record_failed_login(
                max_attempts=max_attempts, lockout_minutes=lockout_minutes
            )
            AuthService._record_login(
                user=user,
                email_attempted=email,
                ip=ip,
                user_agent=user_agent,
                success=False,
                failure_reason="invalid_password",
            )
            raise AuthenticationError("Invalid email or password.")

        if not user.is_active:
            AuthService._record_login(
                user=user,
                email_attempted=email,
                ip=ip,
                user_agent=user_agent,
                success=False,
                failure_reason="account_inactive",
            )
            raise AuthenticationError("This account has been deactivated.")

        # Success — reset counters and record
        user.reset_failed_logins()
        user.last_login_ip = ip
        user.save(update_fields=["last_login_ip"])

        AuthService._record_login(
            user=user,
            email_attempted=email,
            ip=ip,
            user_agent=user_agent,
            success=True,
        )

        tokens = AuthService._generate_tokens(user)
        logger.info("User %s logged in from %s", user.email, ip)
        return LoginResult(user=user, tokens=tokens)

    # ── Logout ───────────────────────────────────────────────────────────────

    @staticmethod
    def logout(refresh_token: str) -> None:
        """
        Blacklist the given refresh token.

        Raises:
            TokenError: if token is invalid or already blacklisted.
        """
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError as exc:
            raise AuthenticationError(str(exc)) from exc

    # ── Token refresh ────────────────────────────────────────────────────────

    @staticmethod
    def refresh(refresh_token: str) -> TokenPair:
        """
        Rotate a refresh token and return a new pair.
        Raises AuthenticationError on invalid/blacklisted token.
        """
        try:
            token = RefreshToken(refresh_token)
            access = str(token.access_token)
            # Rotation is handled by SimpleJWT middleware when ROTATE_REFRESH_TOKENS=True
            # We return the new tokens here
            token.blacklist()
            new_refresh = RefreshToken.for_user(
                User.objects.get(id=token["user_id"])
            )
            return TokenPair(access=str(new_refresh.access_token), refresh=str(new_refresh))
        except (TokenError, User.DoesNotExist) as exc:
            raise AuthenticationError(str(exc)) from exc

    # ── Password reset ───────────────────────────────────────────────────────

    @staticmethod
    def request_password_reset(email: str) -> None:
        """
        Create a password reset token and send the email.

        NOTE: Always returns successfully to avoid user enumeration.
        """
        try:
            user = User.objects.get(email__iexact=email, is_active=True)
        except User.DoesNotExist:
            logger.debug("Password reset requested for unknown email: %s", email)
            return  # Silent — do not reveal whether user exists

        expiry_minutes = getattr(settings, "PASSWORD_RESET_TIMEOUT_MINUTES", 60)
        token = PasswordResetToken.create_for_user(user, expiry_minutes=expiry_minutes)

        AuthService._send_password_reset_email(user, token)
        logger.info("Password reset token created for user %s", user.email)

    @staticmethod
    def confirm_password_reset(token_value: str, new_password: str) -> None:
        """
        Validate the reset token and set the new password.

        Raises:
            AuthenticationError: if token is invalid, expired, or already used.
        """
        try:
            token = PasswordResetToken.objects.select_related("user").get(
                token=token_value
            )
        except PasswordResetToken.DoesNotExist:
            raise AuthenticationError("Invalid or expired password reset token.")

        if not token.is_valid():
            raise AuthenticationError("Invalid or expired password reset token.")

        user = token.user
        user.set_password(new_password)
        user.reset_failed_logins()  # Clear lockout on successful reset
        user.save()

        token.is_used = True
        token.save(update_fields=["is_used"])

        logger.info("Password reset completed for user %s", user.email)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _generate_tokens(user: User) -> TokenPair:
        refresh = RefreshToken.for_user(user)
        return TokenPair(
            access=str(refresh.access_token),
            refresh=str(refresh),
        )

    @staticmethod
    def _record_login(
        *,
        user: User | None,
        email_attempted: str,
        ip: str | None,
        user_agent: str,
        success: bool,
        failure_reason: str = "",
    ) -> None:
        LoginHistory.objects.create(
            user=user,
            email_attempted=email_attempted,
            ip_address=ip,
            user_agent=user_agent,
            success=success,
            failure_reason=failure_reason,
        )

    @staticmethod
    def _get_ip(request: "HttpRequest | None") -> str | None:
        if request is None:
            return None
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")

    @staticmethod
    def _get_user_agent(request: "HttpRequest | None") -> str:
        if request is None:
            return ""
        return request.META.get("HTTP_USER_AGENT", "")

    @staticmethod
    def _send_password_reset_email(user: User, token: PasswordResetToken) -> None:
        """
        Send a password reset email.
        Uses Django's email backend — configure EMAIL_BACKEND in settings.
        """
        reset_url = (
            f"{settings.FRONTEND_URL}/reset-password?token={token.token}"
            if hasattr(settings, "FRONTEND_URL")
            else f"token={token.token}"
        )
        subject = "Password Reset Request — Abeni Pharmacy"
        message = (
            f"Hi {user.first_name or user.email},\n\n"
            f"You requested a password reset. Use the token below:\n\n"
            f"Token: {token.token}\n"
            f"Link:  {reset_url}\n\n"
            f"This link expires in {getattr(settings, 'PASSWORD_RESET_TIMEOUT_MINUTES', 60)} minutes.\n\n"
            f"If you did not request this, please ignore this email.\n\n"
            f"— Abeni Pharmacy Team"
        )
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send password reset email to %s", user.email)


class AuthenticationError(Exception):
    """Raised by AuthService for any authentication failure."""
