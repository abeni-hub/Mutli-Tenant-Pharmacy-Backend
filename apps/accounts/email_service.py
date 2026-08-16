import logging
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

class EmailService:
    @staticmethod
    def send_tenant_welcome_email(
        to_email: str,
        tenant_name: str,
        temporary_password: str,
        login_url: str = "http://localhost:3000/login",
    ) -> bool:
        subject = f"Welcome to MeridianRx — Account Credentials for {tenant_name}"
        message = (
            f"Welcome to MeridianRx!\n\n"
            f"Your company account for {tenant_name} has been successfully provisioned.\n\n"
            f"Login Email: {to_email}\n"
            f"Temporary Password: {temporary_password}\n"
            f"Login URL: {login_url}\n\n"
            f"Note: You will be required to change your password upon your first login.\n"
        )
        html_message = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; rounded: 8px;">
            <h2 style="color: #0f172a;">Welcome to MeridianRx</h2>
            <p>Your company account for <strong>{tenant_name}</strong> has been successfully provisioned.</p>
            <div style="background-color: #f8fafc; padding: 15px; border-radius: 6px; margin: 20px 0;">
                <p style="margin: 4px 0;"><strong>Email:</strong> {to_email}</p>
                <p style="margin: 4px 0;"><strong>Temporary Password:</strong> <code style="background: #e2e8f0; padding: 2px 6px; border-radius: 4px;">{temporary_password}</code></p>
                <p style="margin: 4px 0;"><strong>Login URL:</strong> <a href="{login_url}">{login_url}</a></p>
            </div>
            <p style="color: #64748b; font-size: 13px;">You will be required to set a new permanent password when you log in for the first time.</p>
        </div>
        """
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[to_email],
                html_message=html_message,
                fail_silently=True,
            )
            logger.info(f"Welcome email dispatched to {to_email} via MailHog SMTP ({settings.EMAIL_HOST}:{settings.EMAIL_PORT})")
            return True
        except Exception as exc:
            logger.warning(f"Failed to dispatch email to {to_email}: {exc}")
            return False

    @staticmethod
    def send_user_invitation_email(
        to_email: str,
        tenant_name: str,
        role: str,
        token: str,
        invite_url: str = "http://localhost:3000/auth/setup-password",
    ) -> bool:
        setup_link = f"{invite_url}?token={token}"
        subject = f"You have been invited to join {tenant_name} on MeridianRx"
        message = (
            f"You have been invited to join {tenant_name} as a {role.capitalize()}.\n\n"
            f"Click the link below to accept your invitation and activate your account:\n"
            f"{setup_link}\n"
        )
        html_message = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; rounded: 8px;">
            <h2 style="color: #0f172a;">Team Invitation</h2>
            <p>You have been invited to join <strong>{tenant_name}</strong> as a <strong>{role.capitalize()}</strong>.</p>
            <div style="margin: 25px 0;">
                <a href="{setup_link}" style="background-color: #2563eb; color: #ffffff; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold;">Accept Invitation & Setup Password</a>
            </div>
            <p style="color: #64748b; font-size: 13px;">Or copy and paste this URL into your browser: <br/> {setup_link}</p>
        </div>
        """
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[to_email],
                html_message=html_message,
                fail_silently=True,
            )
            logger.info(f"User invitation email dispatched to {to_email} via MailHog SMTP ({settings.EMAIL_HOST}:{settings.EMAIL_PORT})")
            return True
        except Exception as exc:
            logger.warning(f"Failed to dispatch invitation email to {to_email}: {exc}")
            return False
