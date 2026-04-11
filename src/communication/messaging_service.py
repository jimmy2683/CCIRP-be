import asyncio
import base64
import json
import re
from html import unescape
from typing import Optional, Tuple
from urllib import error, parse, request

from src.communication.email_service import EmailService
from src.config import settings


def normalize_phone_number(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    cleaned = re.sub(r"[^\d+]", "", value.strip())
    if not cleaned:
        return None

    if cleaned.startswith("+"):
        return cleaned

    if cleaned.isdigit():
        return f"+{cleaned}"

    return None


def whatsapp_address(value: Optional[str]) -> Optional[str]:
    phone_number = normalize_phone_number(value)
    if not phone_number:
        return None
    return phone_number if phone_number.startswith("whatsapp:") else f"whatsapp:{phone_number}"


def html_to_text(html: str) -> str:
    if not html:
        return ""

    with_links = re.sub(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        lambda match: f"{re.sub(r'<[^>]+>', '', match.group(2))} ({unescape(match.group(1))})",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    normalized_breaks = re.sub(r"</(p|div|h\d|li|tr|br)>", "\n", with_links, flags=re.IGNORECASE)
    stripped_tags = re.sub(r"<[^>]+>", " ", normalized_breaks)
    unescaped = unescape(stripped_tags)
    lines = [re.sub(r"\s+", " ", line).strip() for line in unescaped.splitlines()]
    return "\n".join(line for line in lines if line).strip()


class MessagingService:
    @staticmethod
    async def send_email(to_email: str, subject: str, body_html: str) -> Tuple[bool, str]:
        return await EmailService.send_email([to_email], subject, body_html)

    @staticmethod
    async def send_sms(to_phone: Optional[str], body_text: str) -> Tuple[bool, str]:
        normalized_phone = normalize_phone_number(to_phone)
        if not normalized_phone:
            return False, "Recipient is missing a valid phone number for SMS"
        if not settings.TWILIO_SMS_FROM.strip():
            return False, "TWILIO_SMS_FROM is not configured"

        return await MessagingService._send_with_twilio(
            to_address=normalized_phone,
            from_address=settings.TWILIO_SMS_FROM.strip(),
            body_text=body_text,
        )

    @staticmethod
    async def send_whatsapp(to_phone: Optional[str], body_text: str) -> Tuple[bool, str]:
        normalized_phone = whatsapp_address(to_phone)
        if not normalized_phone:
            return False, "Recipient is missing a valid phone number for WhatsApp"
        if not settings.TWILIO_WHATSAPP_FROM.strip():
            return False, "TWILIO_WHATSAPP_FROM is not configured"

        return await MessagingService._send_with_twilio(
            to_address=normalized_phone,
            from_address=whatsapp_address(settings.TWILIO_WHATSAPP_FROM.strip()) or settings.TWILIO_WHATSAPP_FROM.strip(),
            body_text=body_text,
        )

    @staticmethod
    async def _send_with_twilio(
        *,
        to_address: str,
        from_address: str,
        body_text: str,
    ) -> Tuple[bool, str]:
        if not settings.TWILIO_ACCOUNT_SID.strip() or not settings.TWILIO_AUTH_TOKEN.strip():
            return False, "Twilio credentials are not configured"

        def do_request() -> Tuple[bool, str]:
            payload = parse.urlencode(
                {
                    "To": to_address,
                    "From": from_address,
                    "Body": body_text,
                }
            ).encode("utf-8")

            auth_header = base64.b64encode(
                f"{settings.TWILIO_ACCOUNT_SID}:{settings.TWILIO_AUTH_TOKEN}".encode("utf-8")
            ).decode("utf-8")

            req = request.Request(
                f"{settings.TWILIO_API_BASE_URL.rstrip('/')}/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json",
                data=payload,
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                method="POST",
            )

            try:
                with request.urlopen(req, timeout=30) as response:
                    raw_body = response.read().decode("utf-8")
                    parsed = json.loads(raw_body or "{}")
                    sid = parsed.get("sid")
                    if sid:
                        return True, f"Message sent successfully ({sid})"
                    return True, "Message sent successfully"
            except error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(error_body)
                    message = parsed.get("message") or error_body
                except json.JSONDecodeError:
                    message = error_body or str(exc)
                return False, f"Failed to send message: {message}"
            except Exception as exc:
                return False, f"Failed to send message: {str(exc)}"

        return await asyncio.to_thread(do_request)
