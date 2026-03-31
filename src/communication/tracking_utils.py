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


def _rewrite_anchor_links(html: str, click_base_url: str) -> str:
    href_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)

    def repl(match: re.Match) -> str:
        original_url = match.group(1).strip()
        if not original_url:
            return match.group(0)

        lower = original_url.lower()
        if (
            lower.startswith("#")
            or lower.startswith("mailto:")
            or lower.startswith("tel:")
            or lower.startswith("javascript:")
            or "/track/click/" in lower
        ):
            return match.group(0)

        wrapped = f"{click_base_url}?u={quote(original_url, safe='')}"
        return f'href="{wrapped}"'

    return href_pattern.sub(repl, html)


def inject_tracking(
    html: str,
    campaign_id: str,
    recipient_email: str,
    owner_user_id: str,
    tracking_base_url: str,
) -> str:
    now = int(time.time())
    exp = now + int(settings.TRACKING_TOKEN_TTL_SECONDS)

    payload = {
        "c": campaign_id,
        "r": recipient_email,
        "o": owner_user_id,
        "exp": exp,
    }
    token = create_tracking_token(payload)

    open_url = f"{tracking_base_url}/track/open/{token}.png"
    click_base = f"{tracking_base_url}/track/click/{token}"

    rewritten = _rewrite_anchor_links(html, click_base)
    pixel_tag = (
        f'<img src="{open_url}" alt="" width="1" height="1" '
        f'style="width:1px;height:1px;opacity:0;border:0;" loading="eager" decoding="sync" />'
    )

    body_close = re.search(r"</body>", rewritten, flags=re.IGNORECASE)
    if body_close:
        idx = body_close.start()
        return rewritten[:idx] + pixel_tag + rewritten[idx:]
    return rewritten + pixel_tag
