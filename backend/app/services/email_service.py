"""Email delivery service backed by AWS SES."""

from __future__ import annotations

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmailService:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def enabled(self) -> bool:
        return bool(
            self._settings.aws_access_key_id.strip()
            and self._settings.aws_secret_access_key.strip()
            and self._settings.aws_ses_from_email.strip()
        )

    def send_password_reset_email(
        self,
        *,
        to_email: str,
        to_name: str,
        reset_url: str,
        expires_in_minutes: int,
    ) -> bool:
        subject = "Reset your QA Copilot password"
        html = (
            f"<p>Hi {to_name},</p>"
            "<p>We received a request to reset your password.</p>"
            f'<p><a href="{reset_url}">Reset password</a></p>'
            f"<p>This link expires in {expires_in_minutes} minutes.</p>"
            "<p>If you did not request this, you can ignore this email.</p>"
        )
        text = (
            f"Hi {to_name},\n\n"
            "We received a request to reset your password.\n"
            f"Reset password: {reset_url}\n\n"
            f"This link expires in {expires_in_minutes} minutes.\n"
            "If you did not request this, you can ignore this email.\n"
        )
        return self._send_email(
            to_email=to_email, subject=subject, html=html, text=text
        )

    def send_invite_email(
        self,
        *,
        to_email: str,
        to_name: str,
        invite_url: str,
        expires_in_minutes: int,
    ) -> bool:
        subject = "You are invited to QA Copilot"
        html = (
            f"<p>Hi {to_name},</p>"
            "<p>You have been invited to join QA Copilot.</p>"
            f'<p><a href="{invite_url}">Accept invitation</a></p>'
            f"<p>This invitation link expires in {expires_in_minutes} minutes.</p>"
        )
        text = (
            f"Hi {to_name},\n\n"
            "You have been invited to join QA Copilot.\n"
            f"Accept invitation: {invite_url}\n\n"
            f"This invitation link expires in {expires_in_minutes} minutes.\n"
        )
        return self._send_email(
            to_email=to_email, subject=subject, html=html, text=text
        )

    def _send_email(self, *, to_email: str, subject: str, html: str, text: str) -> bool:
        if not self.enabled:
            logger.info("ses_email_skipped_configuration_missing", to_email=to_email)
            return False
        try:
            client = boto3.client(
                "ses",
                region_name=self._settings.aws_region,
                aws_access_key_id=self._settings.aws_access_key_id,
                aws_secret_access_key=self._settings.aws_secret_access_key,
            )
            source_name = self._settings.aws_ses_from_name.strip()
            source_email = self._settings.aws_ses_from_email.strip()
            source = f"{source_name} <{source_email}>" if source_name else source_email
            client.send_email(
                Source=source,
                Destination={"ToAddresses": [to_email]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text, "Charset": "UTF-8"},
                        "Html": {"Data": html, "Charset": "UTF-8"},
                    },
                },
            )
            return True
        except (BotoCoreError, ClientError) as exc:
            logger.warning(
                "ses_email_send_failed", to_email=to_email, error=str(exc)[:200]
            )
            return False


_email_service: EmailService | None = None


def get_email_service() -> EmailService:
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
