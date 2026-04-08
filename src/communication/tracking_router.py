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


@router.get("/open/{token}.png")
async def track_open(token: str, request: Request):
    db = _require_db()
    try:
        payload = verify_tracking_token(token)
    except ValueError:
        return Response(content=TRANSPARENT_PNG_BYTES, media_type="image/png")

    await record_engagement_event(
        db=db,
        event_type="open",
        campaign_id=str(payload["c"]),
        recipient_email=str(payload["r"]),
        owner_user_id=str(payload["o"]),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
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

    await record_engagement_event(
        db=db,
        event_type="click",
        campaign_id=str(payload["c"]),
        recipient_email=str(payload["r"]),
        owner_user_id=str(payload["o"]),
        link_url=destination_url,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return RedirectResponse(url=destination_url, status_code=302)
