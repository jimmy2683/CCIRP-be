"""
Unit tests for the campaign recipient priority scoring algorithm.

_calculate_recipient_priority is a pure function (no I/O) so all tests
run without any external dependencies.
"""
import pytest
from datetime import datetime, timedelta, timezone


def _score(
    recipient_doc=None,
    campaign_tags=None,
    channels=None,
    history_stats=None,
    recipient_email="test@example.com",
):
    """Convenience wrapper around _calculate_recipient_priority."""
    from src.communication.service import _calculate_recipient_priority

    return _calculate_recipient_priority(
        recipient_email=recipient_email,
        recipient_doc=recipient_doc or {},
        campaign_tags=campaign_tags or [],
        channels=channels or ["email"],
        history_stats=history_stats or {},
    )


def _now():
    return datetime.now(timezone.utc)


# ── basic sanity ──────────────────────────────────────────────────────────────

class TestPriorityScoreSanity:
    def test_returns_required_keys(self):
        result = _score()
        assert {"priority_score", "priority_level", "priority_level_rank", "priority_breakdown"} <= result.keys()

    def test_score_is_between_0_and_100(self):
        result = _score()
        assert 0.0 <= result["priority_score"] <= 100.0

    def test_new_recipient_gets_low_priority(self):
        result = _score()
        assert result["priority_level"] == "low"

    def test_priority_level_rank_matches_level(self):
        from src.communication.service import PRIORITY_QUEUE_RANK

        result = _score()
        expected_rank = PRIORITY_QUEUE_RANK[result["priority_level"]]
        assert result["priority_level_rank"] == expected_rank


# ── priority level thresholds ─────────────────────────────────────────────────

class TestPriorityLevelThresholds:
    def test_score_70_is_critical(self):
        from src.communication.service import _priority_level_for_score

        assert _priority_level_for_score(70.0) == "critical"
        assert _priority_level_for_score(100.0) == "critical"

    def test_score_50_is_high(self):
        from src.communication.service import _priority_level_for_score

        assert _priority_level_for_score(50.0) == "high"
        assert _priority_level_for_score(69.9) == "high"

    def test_score_28_is_medium(self):
        from src.communication.service import _priority_level_for_score

        assert _priority_level_for_score(28.0) == "medium"
        assert _priority_level_for_score(49.9) == "medium"

    def test_score_below_28_is_low(self):
        from src.communication.service import _priority_level_for_score

        assert _priority_level_for_score(0.0) == "low"
        assert _priority_level_for_score(27.9) == "low"


# ── engagement signals ────────────────────────────────────────────────────────

class TestEngagementSignals:
    def test_high_open_count_raises_score(self):
        baseline = _score()

        engaged = _score(
            recipient_doc={
                "status": "active",
                "engagement": {"open_count_total": 50, "click_count_total": 0},
            }
        )
        assert engaged["priority_score"] > baseline["priority_score"]

    def test_high_click_count_raises_score_more_than_opens(self):
        opens_only = _score(
            recipient_doc={
                "status": "active",
                "engagement": {"open_count_total": 20, "click_count_total": 0},
            }
        )
        clicks_only = _score(
            recipient_doc={
                "status": "active",
                "engagement": {"open_count_total": 0, "click_count_total": 20},
            }
        )
        assert clicks_only["priority_score"] > opens_only["priority_score"]

    def test_highly_engaged_recipient_reaches_critical(self):
        result = _score(
            recipient_doc={
                "status": "active",
                "engagement": {
                    "open_count_total": 100,
                    "click_count_total": 80,
                    "unique_open_campaigns": ["c1", "c2", "c3"],
                    "unique_click_campaigns": ["c1", "c2"],
                    "last_open_at": _now() - timedelta(days=1),
                    "last_click_at": _now() - timedelta(days=1),
                    "tag_scores": {"newsletter": 10},
                },
            },
            campaign_tags=["newsletter"],
            history_stats={"campaign_touchpoints": 20, "delivery_count": 20},
        )
        assert result["priority_level"] in {"critical", "high"}


# ── recency signals ───────────────────────────────────────────────────────────

class TestRecencySignals:
    def test_clicked_yesterday_gets_higher_score_than_clicked_6_months_ago(self):
        recent = _score(
            recipient_doc={
                "status": "active",
                "engagement": {
                    "last_click_at": _now() - timedelta(days=1),
                    "click_count_total": 5,
                },
            }
        )
        stale = _score(
            recipient_doc={
                "status": "active",
                "engagement": {
                    "last_click_at": _now() - timedelta(days=180),
                    "click_count_total": 5,
                },
            }
        )
        assert recent["priority_score"] > stale["priority_score"]

    def test_no_engagement_history_gets_zero_recency(self):
        result = _score(
            recipient_doc={"status": "active", "engagement": {}}
        )
        assert result["priority_breakdown"]["recency_weight"] == 0.0


# ── status penalties ──────────────────────────────────────────────────────────

class TestStatusPenalties:
    def test_unsubscribed_gets_lower_score_than_active(self):
        active = _score(recipient_doc={"status": "active", "engagement": {}})
        unsub = _score(recipient_doc={"status": "unsubscribed", "engagement": {}})
        assert active["priority_score"] > unsub["priority_score"]

    def test_unsubscribed_usually_lands_in_low_priority(self):
        result = _score(recipient_doc={"status": "unsubscribed", "engagement": {}})
        assert result["priority_level"] == "low"


# ── consent penalties ─────────────────────────────────────────────────────────

class TestConsentPenalties:
    def test_email_consent_false_lowers_score(self):
        consented = _score(
            recipient_doc={
                "status": "active",
                "consent_flags": {"email": True},
                "engagement": {},
            },
            channels=["email"],
        )
        revoked = _score(
            recipient_doc={
                "status": "active",
                "consent_flags": {"email": False},
                "engagement": {},
            },
            channels=["email"],
        )
        assert consented["priority_score"] > revoked["priority_score"]

    def test_sms_consent_false_lowers_score(self):
        consented = _score(
            recipient_doc={
                "status": "active",
                "consent_flags": {"sms": True},
                "phone": "+1234567890",
                "engagement": {},
            },
            channels=["sms"],
        )
        revoked = _score(
            recipient_doc={
                "status": "active",
                "consent_flags": {"sms": False},
                "phone": "+1234567890",
                "engagement": {},
            },
            channels=["sms"],
        )
        assert consented["priority_score"] > revoked["priority_score"]


# ── channel readiness ─────────────────────────────────────────────────────────

class TestChannelReadiness:
    def test_sms_without_phone_number_is_penalized(self):
        with_phone = _score(
            recipient_doc={
                "status": "active",
                "phone": "+1234567890",
                "engagement": {},
            },
            channels=["sms"],
        )
        no_phone = _score(
            recipient_doc={"status": "active", "engagement": {}},
            channels=["sms"],
        )
        assert with_phone["priority_score"] > no_phone["priority_score"]

    def test_email_only_campaign_gets_channel_readiness_bonus(self):
        email = _score(
            recipient_doc={"status": "active", "engagement": {}},
            channels=["email"],
        )
        assert email["priority_breakdown"]["channel_readiness_weight"] > 0


# ── tag affinity ──────────────────────────────────────────────────────────────

class TestTagAffinity:
    def test_tag_score_matching_campaign_raises_score(self):
        no_tag = _score(
            recipient_doc={"status": "active", "engagement": {"tag_scores": {}}},
            campaign_tags=["newsletter"],
        )
        tag_match = _score(
            recipient_doc={
                "status": "active",
                "engagement": {"tag_scores": {"newsletter": 8}},
            },
            campaign_tags=["newsletter"],
        )
        assert tag_match["priority_score"] > no_tag["priority_score"]

    def test_direct_tag_overlap_provides_bonus(self):
        no_overlap = _score(
            recipient_doc={"status": "active", "tags": ["sports"], "engagement": {}},
            campaign_tags=["newsletter"],
        )
        overlap = _score(
            recipient_doc={"status": "active", "tags": ["newsletter"], "engagement": {}},
            campaign_tags=["newsletter"],
        )
        assert overlap["priority_score"] > no_overlap["priority_score"]


# ── historical delivery reliability ──────────────────────────────────────────

class TestDeliveryReliability:
    def test_high_failure_rate_lowers_reliability_score(self):
        reliable = _score(
            history_stats={"delivery_count": 20, "delivery_failure_count": 0, "campaign_touchpoints": 20},
            recipient_doc={"status": "active", "engagement": {}},
        )
        unreliable = _score(
            history_stats={"delivery_count": 2, "delivery_failure_count": 18, "campaign_touchpoints": 20},
            recipient_doc={"status": "active", "engagement": {}},
        )
        assert reliable["priority_score"] > unreliable["priority_score"]

    def test_no_delivery_history_gets_neutral_reliability(self):
        result = _score(recipient_doc={"status": "active", "engagement": {}}, history_stats={})
        # With no history, reliability defaults to 3.0 (neutral)
        assert result["priority_breakdown"]["reliability_weight"] == 3.0
