from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from src.config import settings
from typing import List

conf = ConnectionConfig(
    MAIL_USERNAME=settings.SMTP_USER,
    MAIL_PASSWORD=settings.SMTP_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.SMTP_PORT,
    MAIL_SERVER=settings.SMTP_HOST,
    MAIL_STARTTLS=settings.SMTP_TLS,
    MAIL_SSL_TLS=settings.SMTP_SSL,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True
)

fast_mail = FastMail(conf)

class EmailService:
    @staticmethod
    async def send_email(to_emails: List[str], subject: str, body_html: str):
        message = MessageSchema(
            subject=subject,
            recipients=to_emails,
            body=body_html,
            subtype=MessageType.html
        )
        
        try:
            await fast_mail.send_message(message)
            return True, "Email sent successfully"
        except Exception as e:
            return False, f"Failed to send email: {str(e)}"
