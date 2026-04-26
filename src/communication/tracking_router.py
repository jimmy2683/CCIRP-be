from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response

from src.database import get_database
from src.communication.tracking_service import record_engagement_event
from src.communication.tracking_utils import TRANSPARENT_PNG_BYTES, verify_tracking_token


router = APIRouter(prefix="/track", tags=["Tracking"])


def _require_db():
    db = get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return db


async def _tracking_allowed(db, owner_user_id: str, recipient_email: str) -> bool:
    """Return False only when the recipient has explicitly set consent_flags.tracking = False."""
    rec = await db["recipients"].find_one(
        {"user_id": owner_user_id, "email": recipient_email},
        {"consent_flags": 1},
    )
    if not rec:
        return True
    return rec.get("consent_flags", {}).get("tracking", True) is not False


@router.get("/open/{token}.png")
async def track_open(token: str, request: Request):
    db = _require_db()
    try:
        payload = verify_tracking_token(token)
    except ValueError:
        return Response(content=TRANSPARENT_PNG_BYTES, media_type="image/png")

    if await _tracking_allowed(db, str(payload["o"]), str(payload["r"])):
        await record_engagement_event(
            db=db,
            event_type="open",
            campaign_id=str(payload["c"]),
            recipient_email=str(payload["r"]),
            owner_user_id=str(payload["o"]),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            channel=str(payload.get("ch", "email")),
        )

    return Response(content=TRANSPARENT_PNG_BYTES, media_type="image/png")


@router.get("/click/{token}")
async def track_click(token: str, request: Request, u: str = Query(..., description="Destination URL")):
    db = _require_db()
    try:
        payload = verify_tracking_token(token)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    destination_url = u.strip()
    if destination_url and not destination_url.lower().startswith(("http://", "https://")):
        destination_url = f"https://{destination_url}"

    if await _tracking_allowed(db, str(payload["o"]), str(payload["r"])):
        await record_engagement_event(
            db=db,
            event_type="click",
            campaign_id=str(payload["c"]),
            recipient_email=str(payload["r"]),
            owner_user_id=str(payload["o"]),
            link_url=destination_url,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            channel=str(payload.get("ch", "email")),
        )

    return RedirectResponse(url=destination_url, status_code=302)


@router.get("/unsubscribe/{token}")
async def track_unsubscribe(token: str, request: Request):
    db = _require_db()
    try:
        payload = verify_tracking_token(token)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    recipient_email = str(payload["r"])
    owner_id = str(payload["o"])

    await db["recipients"].update_many(
        {"email": recipient_email, "user_id": owner_id},
        {"$set": {
            "status": "unsubscribed", 
            "consent_flags.email": False, 
            "consent_flags.sms": False, 
            "consent_flags.whatsapp": False
        }}
    )

    from fastapi.responses import HTMLResponse
    html_content = """
    <!DOCTYPE html>
    <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Unsubscribed Successfully</title>
        </head>
        <body style="font-family: system-ui, -apple-system, sans-serif; text-align: center; padding: 40px 20px; background-color: #f3f4f6; margin: 0;">
            <div style="max-width: 480px; margin: 0 auto; background: white; padding: 40px 30px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);">
                <div style="width: 48px; height: 48px; border-radius: 9999px; background-color: #d1fae5; color: #059669; display: flex; align-items: center; justify-content: center; margin: 0 auto 20px;">
                    <svg style="width: 24px; height: 24px;" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                </div>
                <h2 style="color: #111827; margin: 0 0 12px; font-size: 24px; font-weight: 700;">Unsubscribed Successfully</h2>
                <p style="color: #4b5563; font-size: 15px; line-height: 1.5; margin: 0;">
                    You have been successfully removed from this mailing list and will no longer receive communications.
                </p>
                <div style="margin-top: 32px; padding-top: 24px; border-top: 1px solid #f3f4f6; color: #9ca3af; font-size: 13px;">
                    You can safely close this page.
                </div>
            </div>
        </body>
    </html>
    """

    try:
        await record_engagement_event(
            db=db,
            event_type="unsubscribe",
            campaign_id=str(payload["c"]),
            recipient_email=recipient_email,
            owner_user_id=owner_id,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            channel=str(payload.get("ch", "email")),
        )
    except Exception:
        pass # allow graceful degradation if metrics logging fails for any reason

    return HTMLResponse(content=html_content)
