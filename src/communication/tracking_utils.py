import base64
import hashlib
import hmac
import json
import re
import time
from urllib.parse import quote

from src.config import settings


TRANSPARENT_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WqfNf8AAAAASUVORK5CYII="
)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("utf-8"))


def create_tracking_token(payload: dict) -> str:
    encoded_payload = _b64url_encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    sig = hmac.new(
        settings.TRACKING_SIGNING_KEY.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    encoded_sig = _b64url_encode(sig)
    return f"{encoded_payload}.{encoded_sig}"


def verify_tracking_token(token: str) -> dict:
    try:
        encoded_payload, encoded_sig = token.split(".", 1)
    except ValueError:
        raise ValueError("Invalid token format")

    expected_sig = hmac.new(
        settings.TRACKING_SIGNING_KEY.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    actual_sig = _b64url_decode(encoded_sig)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Invalid token signature")

    payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
    exp = payload.get("exp")
    if exp and int(time.time()) > int(exp):
        raise ValueError("Token expired")
    return payload


def _build_tracking_token(
    campaign_id: str,
    recipient_email: str,
    owner_user_id: str,
    channel: str,
) -> str:
    now = int(time.time())
    exp = now + int(settings.TRACKING_TOKEN_TTL_SECONDS)

    payload = {
        "c": campaign_id,
        "r": recipient_email,
        "o": owner_user_id,
        "ch": channel,
        "exp": exp,
    }
    return create_tracking_token(payload)


def _wrap_click_url(original_url: str, click_base_url: str) -> str:
    clean_url = original_url.strip()
    if not clean_url:
        return original_url

    lower = clean_url.lower()
    if (
        lower.startswith("#")
        or lower.startswith("mailto:")
        or lower.startswith("tel:")
        or lower.startswith("javascript:")
        or "/track/click/" in lower
    ):
        return original_url

    return f"{click_base_url}?u={quote(clean_url, safe='')}"


def _rewrite_anchor_links(html: str, click_base_url: str) -> str:
    href_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)

    def repl(match: re.Match) -> str:
        original_url = match.group(1).strip()
        if not original_url:
            return match.group(0)

        wrapped = _wrap_click_url(original_url, click_base_url)
        if wrapped == original_url:
            return match.group(0)
        return f'href="{wrapped}"'

    return href_pattern.sub(repl, html)


def _rewrite_plain_text_links(text: str, click_base_url: str) -> str:
    if not text:
        return text

    url_pattern = re.compile(r"(?P<url>(?:https?://|www\.)[^\s<>\"]+)", re.IGNORECASE)

    def repl(match: re.Match) -> str:
        matched_url = match.group("url")
        candidate = matched_url
        trailing = ""
        while candidate and (
            candidate[-1] in ".,!?;:"
            or (candidate[-1] == ")" and candidate.count(")") > candidate.count("("))
        ):
            trailing = candidate[-1] + trailing
            candidate = candidate[:-1]

        wrapped = _wrap_click_url(candidate, click_base_url)
        return f"{wrapped}{trailing}"

    return url_pattern.sub(repl, text)


def inject_tracking(
    html: str,
    campaign_id: str,
    recipient_email: str,
    owner_user_id: str,
    tracking_base_url: str,
    channel: str = "email",
) -> str:
    token = _build_tracking_token(campaign_id, recipient_email, owner_user_id, channel)

    open_url = f"{tracking_base_url}/track/open/{token}.png"
    click_base = f"{tracking_base_url}/track/click/{token}"
    unsubscribe_url = f"{tracking_base_url}/track/unsubscribe/{token}"

    rewritten = _rewrite_anchor_links(html, click_base)
    pixel_tag = (
        f'<img src="{open_url}" alt="" width="1" height="1" '
        f'style="width:1px;height:1px;opacity:0;border:0;" loading="eager" decoding="sync" />'
    )
    
    unsubscribe_content = ""
    if channel == "email":
        unsubscribe_content = (
            f'<div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #eaeaea; font-family: sans-serif; font-size: 12px; color: #6b7280; text-align: center;">'
            f'You are receiving this email because you are subscribed to our communications.<br/>'
            f'To stop receiving these emails, you may <a href="{unsubscribe_url}" style="color: #6b7280; text-decoration: underline;">unsubscribe here</a>.'
            f'</div>'
        )

    inject_payload = unsubscribe_content + pixel_tag

    body_close = re.search(r"</body>", rewritten, flags=re.IGNORECASE)
    if body_close:
        idx = body_close.start()
        return rewritten[:idx] + inject_payload + rewritten[idx:]
    return rewritten + inject_payload


def inject_click_tracking_text(
    text: str,
    campaign_id: str,
    recipient_email: str,
    owner_user_id: str,
    tracking_base_url: str,
    channel: str,
) -> str:
    token = _build_tracking_token(campaign_id, recipient_email, owner_user_id, channel)
    click_base = f"{tracking_base_url}/track/click/{token}"
    return _rewrite_plain_text_links(text, click_base)
