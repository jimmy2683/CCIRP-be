"""
Tests for user engagement profile features:
  - Bounce / delivery-failure rollup to recipient.engagement
  - Unsubscribe timestamp stored on recipient
  - Link-level click analytics aggregation
  - Recipient campaign history endpoint
  - Unsubscribe rate in analytics overview
  - SMS / WhatsApp plain-text link rewriting (click tracking)
  - EngagementStats model fields
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId


# ── helpers ───────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


def _async_cursor(items):
    cur = MagicMock()
    cur.to_list = AsyncMock(return_value=items)
    return cur


def _chain_cursor(items):
    cur = MagicMock()
    cur.sort = MagicMock(return_value=cur)
    cur.limit = MagicMock(return_value=cur)
    cur.skip = MagicMock(return_value=cur)
    cur.to_list = AsyncMock(return_value=items)
    return cur


def _default_col():
    col = MagicMock()
    col.find_one = AsyncMock(return_value=None)
    col.insert_one = AsyncMock(return_value=MagicMock(inserted_id="fake_id"))
    col.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    col.update_many = AsyncMock(return_value=MagicMock(modified_count=1))
    col.count_documents = AsyncMock(return_value=0)
    col.aggregate = MagicMock(return_value=_async_cursor([]))
    col.find = MagicMock(return_value=_chain_cursor([]))
    return col


def _make_db(collections: dict | None = None) -> MagicMock:
    """Mock db where db["name"] returns the pre-configured or auto-created collection mock."""
    cols = dict(collections or {})
    cache: dict = {}

    def _get_col(name):
        if name in cols:
            return cols[name]
        if name not in cache:
            cache[name] = _default_col()
        return cache[name]

    db = MagicMock()
    db.__getitem__ = MagicMock(side_effect=_get_col)
    return db


# ── EngagementStats model ──────────────────────────────────────────────────────

class TestEngagementStatsModel:
    def test_new_fields_have_correct_defaults(self):
        from src.recipients.models import EngagementStats

        eng = EngagementStats()
        assert eng.bounce_count == 0
        assert eng.delivery_failure_count == 0
        assert eng.last_bounced_at is None
        assert eng.unsubscribed_at is None

    def test_all_legacy_fields_still_present(self):
        from src.recipients.models import EngagementStats

        eng = EngagementStats()
        for field in ("open_count_total", "click_count_total", "unique_open_campaigns",
                      "tag_scores", "last_open_at", "last_click_at"):
            assert hasattr(eng, field)

    def test_schema_mirrors_model_fields(self):
        from src.recipients.models import EngagementStats
        from src.recipients.schemas import EngagementStatsSchema

        model_fields = set(EngagementStats.model_fields.keys())
        schema_fields = set(EngagementStatsSchema.model_fields.keys())
        assert model_fields == schema_fields, (
            f"Model-only: {model_fields - schema_fields}, "
            f"Schema-only: {schema_fields - model_fields}"
        )


# ── Bounce rollup ──────────────────────────────────────────────────────────────

class TestBounceRollup:
    @pytest.mark.asyncio
    async def test_failed_delivery_increments_bounce_fields_on_recipient(self):
        from src.communication.tracking_service import record_delivery_event

        recipient_id = ObjectId()
        campaigns_col = _default_col()
        campaigns_col.find_one = AsyncMock(return_value={"tags": []})

        recipients_col = _default_col()
        recipients_col.find_one = AsyncMock(return_value={"_id": recipient_id})

        db = _make_db({
            "campaigns": campaigns_col,
            "email_events": _default_col(),
            "campaign_recipient_stats": _default_col(),
            "recipients": recipients_col,
        })

        await record_delivery_event(
            db=db,
            campaign_id="camp1",
            recipient_email="a@test.com",
            owner_user_id="user1",
            delivered=False,
            error_message="SMTP timeout",
            channel="email",
        )

        recipients_col.update_one.assert_called_once()
        update_doc = recipients_col.update_one.call_args[0][1]
        assert update_doc["$inc"]["engagement.bounce_count"] == 1
        assert update_doc["$inc"]["engagement.delivery_failure_count"] == 1
        assert "engagement.last_bounced_at" in update_doc["$set"]
        assert isinstance(update_doc["$set"]["engagement.last_bounced_at"], datetime)

    @pytest.mark.asyncio
    async def test_successful_delivery_does_not_update_bounce_fields(self):
        from src.communication.tracking_service import record_delivery_event

        campaigns_col = _default_col()
        campaigns_col.find_one = AsyncMock(return_value={"tags": []})

        recipients_col = _default_col()
        recipients_col.find_one = AsyncMock(return_value={"_id": ObjectId()})

        db = _make_db({
            "campaigns": campaigns_col,
            "email_events": _default_col(),
            "campaign_recipient_stats": _default_col(),
            "recipients": recipients_col,
        })

        await record_delivery_event(
            db=db,
            campaign_id="camp1",
            recipient_email="a@test.com",
            owner_user_id="user1",
            delivered=True,
            channel="email",
        )

        recipients_col.update_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_bounce_skipped_when_recipient_not_in_db(self):
        from src.communication.tracking_service import record_delivery_event

        campaigns_col = _default_col()
        campaigns_col.find_one = AsyncMock(return_value={"tags": []})

        recipients_col = _default_col()
        recipients_col.find_one = AsyncMock(return_value=None)

        db = _make_db({
            "campaigns": campaigns_col,
            "email_events": _default_col(),
            "campaign_recipient_stats": _default_col(),
            "recipients": recipients_col,
        })

        await record_delivery_event(
            db=db,
            campaign_id="camp1",
            recipient_email="ghost@test.com",
            owner_user_id="user1",
            delivered=False,
        )

        recipients_col.update_one.assert_not_called()


# ── Unsubscribe timestamp ──────────────────────────────────────────────────────

class TestUnsubscribeTimestamp:
    def _make_token(self):
        from src.communication.tracking_utils import _build_tracking_token
        return _build_tracking_token("camp1", "a@test.com", "user1", "email")

    def _make_request(self):
        from fastapi import Request
        return Request({"type": "http", "method": "GET", "headers": [], "query_string": b"", "path": "/"})

    @pytest.mark.asyncio
    async def test_unsubscribe_stores_timestamp_on_recipient(self):
        from src.communication.tracking_router import track_unsubscribe

        token = self._make_token()
        recipients_col = _default_col()
        campaigns_col = _default_col()
        campaigns_col.find_one = AsyncMock(return_value={"tags": []})

        db = _make_db({
            "recipients": recipients_col,
            "campaigns": campaigns_col,
            "email_events": _default_col(),
            "tracking_uniques": _default_col(),
            "campaign_recipient_stats": _default_col(),
        })

        with patch("src.communication.tracking_router._require_db", return_value=db):
            await track_unsubscribe(token=token, request=self._make_request())

        recipients_col.update_many.assert_called_once()
        set_doc = recipients_col.update_many.call_args[0][1]["$set"]
        assert "engagement.unsubscribed_at" in set_doc
        ts = set_doc["engagement.unsubscribed_at"]
        assert isinstance(ts, datetime) and ts.tzinfo is not None

    @pytest.mark.asyncio
    async def test_unsubscribe_sets_status_and_all_consent_flags(self):
        from src.communication.tracking_router import track_unsubscribe

        token = self._make_token()
        recipients_col = _default_col()
        campaigns_col = _default_col()
        campaigns_col.find_one = AsyncMock(return_value={"tags": []})

        db = _make_db({
            "recipients": recipients_col,
            "campaigns": campaigns_col,
            "email_events": _default_col(),
            "tracking_uniques": _default_col(),
            "campaign_recipient_stats": _default_col(),
        })

        with patch("src.communication.tracking_router._require_db", return_value=db):
            await track_unsubscribe(token=token, request=self._make_request())

        set_doc = recipients_col.update_many.call_args[0][1]["$set"]
        assert set_doc["status"] == "unsubscribed"
        assert set_doc["consent_flags.email"] is False
        assert set_doc["consent_flags.sms"] is False
        assert set_doc["consent_flags.whatsapp"] is False


# ── SMS / WhatsApp click tracking ─────────────────────────────────────────────

class TestPlainTextClickTracking:
    BASE = "https://track.example.com/click/TOKEN"

    def _rewrite(self, text: str) -> str:
        from src.communication.tracking_utils import _rewrite_plain_text_links
        return _rewrite_plain_text_links(text, self.BASE)

    def test_http_url_is_rewritten_through_tracker(self):
        result = self._rewrite("Visit http://example.com for details")
        assert self.BASE in result
        assert "?u=http" in result

    def test_https_url_is_rewritten_through_tracker(self):
        result = self._rewrite("See https://docs.example.com/guide")
        assert self.BASE in result
        assert "?u=https" in result

    def test_www_url_is_rewritten_through_tracker(self):
        result = self._rewrite("Go to www.example.com now")
        # Original bare domain is redirected through the tracker
        assert self.BASE in result

    def test_trailing_period_preserved_outside_url(self):
        result = self._rewrite("See https://example.com.")
        assert result.endswith(".")
        assert self.BASE in result

    def test_multiple_urls_all_rewritten(self):
        result = self._rewrite("Check https://a.com, then https://b.com.")
        assert result.count(self.BASE) == 2
        assert result.endswith(".")

    def test_plain_text_with_no_urls_unchanged(self):
        text = "Hello, how are you today?"
        assert self._rewrite(text) == text

    def test_inject_click_tracking_text_for_sms(self):
        from src.communication.tracking_utils import inject_click_tracking_text

        result = inject_click_tracking_text(
            text="Click https://example.com",
            campaign_id="c1",
            recipient_email="r@test.com",
            owner_user_id="u1",
            tracking_base_url="https://track.example.com",
            channel="sms",
        )
        assert "/track/click/" in result
        assert "?u=https" in result

    def test_inject_click_tracking_text_for_whatsapp(self):
        from src.communication.tracking_utils import inject_click_tracking_text

        result = inject_click_tracking_text(
            text="Fill the form https://forms.example.com/survey",
            campaign_id="c2",
            recipient_email="r@test.com",
            owner_user_id="u1",
            tracking_base_url="https://track.example.com",
            channel="whatsapp",
        )
        assert "/track/click/" in result


# ── Link analytics aggregation ─────────────────────────────────────────────────

class TestCampaignLinkAnalytics:
    @pytest.mark.asyncio
    async def test_returns_links_ranked_by_click_count(self):
        from src.analytics.router import get_campaign_link_analytics

        campaign_id = str(ObjectId())
        user_id = "user1"

        agg_results = [
            {"_id": "https://a.com", "total_clicks": 10, "unique_clicks": 7, "last_clicked_at": _now()},
            {"_id": "https://b.com", "total_clicks": 4, "unique_clicks": 3, "last_clicked_at": _now()},
        ]

        campaigns_col = _default_col()
        campaigns_col.find_one = AsyncMock(return_value={"created_by": user_id})
        email_events_col = _default_col()
        email_events_col.aggregate = MagicMock(return_value=_async_cursor(agg_results))

        db = _make_db({"campaigns": campaigns_col, "email_events": email_events_col})

        with patch("src.analytics.router.get_database", return_value=db):
            result = await get_campaign_link_analytics(campaign_id=campaign_id, current_user={"id": user_id})

        assert result["campaign_id"] == campaign_id
        assert len(result["links"]) == 2
        first = result["links"][0]
        assert first["url"] == "https://a.com"
        assert first["total_clicks"] == 10
        assert first["unique_clicks"] == 7

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_clicks(self):
        from src.analytics.router import get_campaign_link_analytics

        campaign_id = str(ObjectId())
        campaigns_col = _default_col()
        campaigns_col.find_one = AsyncMock(return_value={"created_by": "u1"})
        email_events_col = _default_col()
        email_events_col.aggregate = MagicMock(return_value=_async_cursor([]))

        db = _make_db({"campaigns": campaigns_col, "email_events": email_events_col})

        with patch("src.analytics.router.get_database", return_value=db):
            result = await get_campaign_link_analytics(campaign_id=campaign_id, current_user={"id": "u1"})

        assert result["links"] == []

    @pytest.mark.asyncio
    async def test_raises_403_for_wrong_owner(self):
        from src.analytics.router import get_campaign_link_analytics
        from fastapi import HTTPException

        campaign_id = str(ObjectId())
        campaigns_col = _default_col()
        campaigns_col.find_one = AsyncMock(return_value={"created_by": "other_user"})

        db = _make_db({"campaigns": campaigns_col})

        with patch("src.analytics.router.get_database", return_value=db):
            with pytest.raises(HTTPException) as exc:
                await get_campaign_link_analytics(campaign_id=campaign_id, current_user={"id": "user1"})

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_404_for_missing_campaign(self):
        from src.analytics.router import get_campaign_link_analytics
        from fastapi import HTTPException

        campaign_id = str(ObjectId())
        campaigns_col = _default_col()
        campaigns_col.find_one = AsyncMock(return_value=None)

        db = _make_db({"campaigns": campaigns_col})

        with patch("src.analytics.router.get_database", return_value=db):
            with pytest.raises(HTTPException) as exc:
                await get_campaign_link_analytics(campaign_id=campaign_id, current_user={"id": "u1"})

        assert exc.value.status_code == 404


# ── Recipient engagement history ───────────────────────────────────────────────

class TestRecipientEngagementHistory:
    @pytest.mark.asyncio
    async def test_resolves_campaign_names_from_db(self):
        from src.analytics.router import get_recipient_engagement_history

        recipient_oid = ObjectId()
        campaign_oid = ObjectId()
        user_id = "user1"
        now = _now()

        recipient_doc = {
            "_id": recipient_oid,
            "email": "r@test.com",
            "user_id": user_id,
            "engagement": {"open_count_total": 5, "click_count_total": 2,
                           "bounce_count": 0, "delivery_failure_count": 0},
        }

        stats = [{
            "campaign_id": str(campaign_oid),
            "delivery_status": "delivered",
            "open_count": 3, "unique_open_count": 1,
            "click_count": 1, "unique_click_count": 1,
            "last_open_at": now, "last_click_at": now,
            "created_at": now,
        }]

        campaign_doc = {
            "_id": campaign_oid,
            "name": "Welcome Campaign",
            "channels": ["email"],
            "tags": ["onboarding"],
            "created_at": now,
        }

        recipients_col = _default_col()
        recipients_col.find_one = AsyncMock(return_value=recipient_doc)
        stats_col = _default_col()
        stats_col.find = MagicMock(return_value=_chain_cursor(stats))
        campaigns_col = _default_col()
        campaigns_col.find = MagicMock(return_value=_chain_cursor([campaign_doc]))

        db = _make_db({
            "recipients": recipients_col,
            "campaign_recipient_stats": stats_col,
            "campaigns": campaigns_col,
        })

        with patch("src.analytics.router.get_database", return_value=db):
            result = await get_recipient_engagement_history(
                recipient_id=str(recipient_oid), limit=20, current_user={"id": user_id}
            )

        assert result["email"] == "r@test.com"
        assert len(result["campaign_history"]) == 1
        entry = result["campaign_history"][0]
        assert entry["campaign_name"] == "Welcome Campaign"
        assert entry["campaign_tags"] == ["onboarding"]
        assert entry["delivery_status"] == "delivered"
        assert entry["unique_open_count"] == 1
        assert entry["unique_click_count"] == 1

    @pytest.mark.asyncio
    async def test_engagement_summary_includes_bounce_and_unsub_fields(self):
        from src.analytics.router import get_recipient_engagement_history

        recipient_oid = ObjectId()
        now = _now()

        recipient_doc = {
            "_id": recipient_oid,
            "email": "r@test.com",
            "user_id": "u1",
            "engagement": {
                "open_count_total": 10, "click_count_total": 4,
                "bounce_count": 2, "delivery_failure_count": 2,
                "last_open_at": now, "last_click_at": now,
                "last_bounced_at": now, "unsubscribed_at": None,
            },
        }

        recipients_col = _default_col()
        recipients_col.find_one = AsyncMock(return_value=recipient_doc)
        stats_col = _default_col()
        stats_col.find = MagicMock(return_value=_chain_cursor([]))
        campaigns_col = _default_col()
        campaigns_col.find = MagicMock(return_value=_chain_cursor([]))

        db = _make_db({
            "recipients": recipients_col,
            "campaign_recipient_stats": stats_col,
            "campaigns": campaigns_col,
        })

        with patch("src.analytics.router.get_database", return_value=db):
            result = await get_recipient_engagement_history(
                recipient_id=str(recipient_oid), limit=20, current_user={"id": "u1"}
            )

        s = result["engagement_summary"]
        assert s["open_count_total"] == 10
        assert s["bounce_count"] == 2
        assert s["delivery_failure_count"] == 2
        assert s["unsubscribed_at"] is None

    @pytest.mark.asyncio
    async def test_unknown_campaigns_fall_back_to_unknown_label(self):
        from src.analytics.router import get_recipient_engagement_history

        recipient_oid = ObjectId()
        missing_campaign_id = str(ObjectId())
        now = _now()

        recipient_doc = {
            "_id": recipient_oid, "email": "r@test.com", "user_id": "u1",
            "engagement": {},
        }
        stats = [{
            "campaign_id": missing_campaign_id,
            "delivery_status": "delivered",
            "open_count": 0, "unique_open_count": 0,
            "click_count": 0, "unique_click_count": 0,
            "created_at": now,
        }]

        recipients_col = _default_col()
        recipients_col.find_one = AsyncMock(return_value=recipient_doc)
        stats_col = _default_col()
        stats_col.find = MagicMock(return_value=_chain_cursor(stats))
        campaigns_col = _default_col()
        campaigns_col.find = MagicMock(return_value=_chain_cursor([]))  # campaign not found

        db = _make_db({
            "recipients": recipients_col,
            "campaign_recipient_stats": stats_col,
            "campaigns": campaigns_col,
        })

        with patch("src.analytics.router.get_database", return_value=db):
            result = await get_recipient_engagement_history(
                recipient_id=str(recipient_oid), limit=20, current_user={"id": "u1"}
            )

        assert result["campaign_history"][0]["campaign_name"] == "Unknown Campaign"

    @pytest.mark.asyncio
    async def test_raises_404_when_recipient_not_found(self):
        from src.analytics.router import get_recipient_engagement_history
        from fastapi import HTTPException

        recipients_col = _default_col()
        recipients_col.find_one = AsyncMock(return_value=None)

        db = _make_db({"recipients": recipients_col})

        with patch("src.analytics.router.get_database", return_value=db):
            with pytest.raises(HTTPException) as exc:
                await get_recipient_engagement_history(
                    recipient_id=str(ObjectId()), limit=20, current_user={"id": "u1"}
                )

        assert exc.value.status_code == 404


# ── Unsubscribe rate in overview ───────────────────────────────────────────────

class TestUnsubscribeRateInOverview:
    def _campaign_doc(self, oid: ObjectId, n_recipients: int = 10):
        return {
            "_id": oid,
            "name": "Camp",
            "status": "sent",
            "channels": ["email"],
            "recipients": [f"r{i}@t.com" for i in range(n_recipients)],
            "created_at": _now(),
            "tags": [],
        }

    @pytest.mark.asyncio
    async def test_unsubscribe_rate_computed_from_event_count(self):
        from src.analytics.router import get_analytics_overview

        camp_oid = ObjectId()
        camp_doc = self._campaign_doc(camp_oid, n_recipients=10)

        campaigns_col = _default_col()
        campaigns_col.count_documents = AsyncMock(return_value=1)
        campaigns_col.find = MagicMock(return_value=_chain_cursor([camp_doc]))

        stats_col = _default_col()
        # First aggregate call: global stats. Second call: per-campaign performance stats.
        stats_col.aggregate = MagicMock(side_effect=[
            _async_cursor([{"_id": None, "total_opens": 0, "total_clicks": 0,
                            "unique_opens": 0, "unique_clicks": 0}]),
            _async_cursor([{"_id": None, "opens": 0, "clicks": 0}]),
        ])
        stats_col.count_documents = AsyncMock(return_value=0)  # failed deliveries

        email_events_col = _default_col()
        # trend aggregate returns empty; count_documents returns 2 unsubscribes
        email_events_col.aggregate = MagicMock(return_value=_async_cursor([]))
        email_events_col.count_documents = AsyncMock(return_value=2)

        db = _make_db({
            "campaigns": campaigns_col,
            "campaign_recipient_stats": stats_col,
            "email_events": email_events_col,
        })

        with patch("src.analytics.router.get_database", return_value=db):
            result = await get_analytics_overview(current_user={"id": "user1"})

        # 2 unsubscribes out of 10 sent = 20.0%
        assert result["unsubscribe_rate"] == "20.0%"

    @pytest.mark.asyncio
    async def test_unsubscribe_rate_is_zero_when_no_unsubscribe_events(self):
        from src.analytics.router import get_analytics_overview

        camp_oid = ObjectId()
        camp_doc = self._campaign_doc(camp_oid, n_recipients=5)

        campaigns_col = _default_col()
        campaigns_col.count_documents = AsyncMock(return_value=1)
        campaigns_col.find = MagicMock(return_value=_chain_cursor([camp_doc]))

        stats_col = _default_col()
        stats_col.aggregate = MagicMock(side_effect=[
            _async_cursor([{"_id": None, "total_opens": 0, "total_clicks": 0,
                            "unique_opens": 0, "unique_clicks": 0}]),
            _async_cursor([{"_id": None, "opens": 0, "clicks": 0}]),
        ])
        stats_col.count_documents = AsyncMock(return_value=0)

        email_events_col = _default_col()
        email_events_col.aggregate = MagicMock(return_value=_async_cursor([]))
        email_events_col.count_documents = AsyncMock(return_value=0)  # no unsubscribes

        db = _make_db({
            "campaigns": campaigns_col,
            "campaign_recipient_stats": stats_col,
            "email_events": email_events_col,
        })

        with patch("src.analytics.router.get_database", return_value=db):
            result = await get_analytics_overview(current_user={"id": "user1"})

        assert result["unsubscribe_rate"] == "0.0%"
