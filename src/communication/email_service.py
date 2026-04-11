import asyncio
import json
from typing import List, Tuple
from urllib import error, request

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType

from src.config import settings


def build_smtp_client() -> FastMail:
    conf = ConnectionConfig(
        MAIL_USERNAME=settings.SMTP_USER,
        MAIL_PASSWORD=settings.SMTP_PASSWORD,
        MAIL_FROM=settings.MAIL_FROM,
        MAIL_PORT=settings.SMTP_PORT,
        MAIL_SERVER=settings.SMTP_HOST,
        MAIL_STARTTLS=settings.SMTP_TLS,
        MAIL_SSL_TLS=settings.SMTP_SSL,
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True,
    )
    return FastMail(conf)


fast_mail = build_smtp_client()


class EmailService:
    @staticmethod
    async def send_email(to_emails: List[str], subject: str, body_html: str) -> Tuple[bool, str]:
        provider = settings.EMAIL_PROVIDER.strip().lower()
        if provider == "resend":
            return await EmailService._send_with_resend(to_emails, subject, body_html)
        return await EmailService._send_with_smtp(to_emails, subject, body_html)

    @staticmethod
    async def _send_with_smtp(to_emails: List[str], subject: str, body_html: str) -> Tuple[bool, str]:
        message = MessageSchema(
            subject=subject,
            recipients=to_emails,
            body=body_html,
            subtype=MessageType.html,
        )

        try:
            await fast_mail.send_message(message)
            return True, "Email sent successfully"
        except Exception as exc:
            return False, f"Failed to send email: {str(exc)}"

    @staticmethod
    async def _send_with_resend(to_emails: List[str], subject: str, body_html: str) -> Tuple[bool, str]:
        if not settings.RESEND_API_KEY:
            return False, "Failed to send email: RESEND_API_KEY is not configured"

        payload = {
            "from": settings.MAIL_FROM,
            "to": to_emails,
            "subject": subject,
            "html": body_html,
        }
        if settings.RESEND_REPLY_TO.strip():
            payload["reply_to"] = [settings.RESEND_REPLY_TO.strip()]

        def do_request() -> Tuple[bool, str]:
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(
                f"{settings.RESEND_API_BASE_URL.rstrip('/')}/emails",
                data=data,
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with request.urlopen(req, timeout=30) as response:
                    raw_body = response.read().decode("utf-8")
                    parsed = json.loads(raw_body or "{}")
                    email_id = parsed.get("id")
                    if email_id:
                        return True, f"Email sent successfully ({email_id})"
                    return True, "Email sent successfully"
            except error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(error_body)
                    message = parsed.get("message") or parsed.get("name") or error_body
                except json.JSONDecodeError:
                    message = error_body or str(exc)
                return False, f"Failed to send email: {message}"
            except Exception as exc:
                return False, f"Failed to send email: {str(exc)}"

        return await asyncio.to_thread(do_request)
