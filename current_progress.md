# CCIRP Backend — Current Progress

## Completed Features

### 1. Project Foundation & Infrastructure
- **FastAPI Core**: Asynchronous FastAPI application with modular router architecture under `src/`.
- **Configuration Management**: Centralized settings via `pydantic-settings` reading from `.env`. All tunable values (DB, JWT, SMTP, Kafka, Celery, Redis, AI, tracking) live in `src/config.py`.
- **Lifecycle Management**: `src/main.py` starts MongoDB connection and the campaign scheduler coroutine on startup; tears them down cleanly on shutdown.
- **CORS**: Controlled via `FRONTEND_URL` env var.

### 2. Database (MongoDB + Motor)
- **Motor client** with `tz_aware=True` — all datetimes returned from MongoDB are UTC-aware, preventing timezone display bugs in the frontend.
- **ObjectId serialization**: String-cast BSON ObjectIds across all Pydantic schemas.
- Indexes created lazily on first use (AI conversations, campaign dispatch queue, email events).

### 3. Authentication & Security
- JWT access tokens (24 h) + refresh tokens (7 d) via `OAuth2PasswordBearer`.
- `passlib` (bcrypt) password hashing.
- Endpoints: `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`.

### 4. Template Engine
- Full CRUD for email/SMS/WhatsApp templates with automatic version increment.
- `design_json` field for drag-and-drop builder state persistence.
- `POST /templates/preview` — server-side `{{field}}` merge with sample data.
- `POST /templates/{id}/test-send` — dispatches a real email to a specified address.
- Template history archived to `template_history` collection on every update.

### 5. Multi-Channel Communication & Campaign Engine

#### Dispatch Pipeline
- **Priority queue**: `campaign_dispatch_queue` collection. Each recipient-campaign pair is a queue job with `priority_score`, `priority_level` (critical/high/medium/low), `available_at`, `attempts`.
- **Scoring**: Composite score from engagement history, tag overlap, consent status, recency, channel readiness.
- **Scheduler**: `run_campaign_scheduler` coroutine (async, inside the FastAPI process) runs every `CAMPAIGN_SCHEDULER_INTERVAL_SECONDS`. Also wired to Celery Beat (`ccirp.scheduler_tick`) if Celery/Redis are available.
- **Celery fallback**: `dispatch_campaign_task.delay(campaign_id)` is attempted first; if Celery is unavailable, a FastAPI `BackgroundTask` is used instead.
- **Stale recovery**: Processing jobs stuck for > `CAMPAIGN_QUEUE_STALE_SECONDS` are automatically reset to `queued`.

#### Campaign Statuses
`draft` → `scheduled` | `queued` → `dispatching` → `sent` | `partially_sent` | `failed`

#### Retry
- `POST /campaigns/{id}/retry` — only callable when status is `failed` or `partially_sent`.
- Resets all `failed`/`cancelled` dispatch queue entries back to `queued` (zeroes attempts, clears outcome).
- Sets campaign status to `queued` (fully failed) or `dispatching` (partial — some already completed).
- Unsets `queue_prepared_at` then re-triggers dispatch via Celery or background task.

#### Channels
- **Email**: HTML with tracking pixel (1×1 PNG, email only), link rewriting, unsubscribe footer injection.
- **SMS / WhatsApp**: Plain-text dispatch via Twilio. Click tracking via `_rewrite_plain_text_links()` — same `/track/click/{token}?u={url}` wrapping as email.

#### Spam Detection
- Pre-flight AI check on every campaign enqueue (`analyze_spam_score`). Campaigns scoring as spam are set to `failed` immediately with an `error_message`.
- Also callable explicitly via `POST /campaigns/check-spam` from the wizard UI.

### 6. Tracking & Engagement

#### Open / Click / Unsubscribe Tracking
- **Pixel**: `GET /track/open/{token}.png` — 1×1 transparent PNG, email only.
- **Click**: `GET /track/click/{token}?u={url}` — records event, redirects.
- **Unsubscribe**: `GET /track/unsubscribe/{token}` — sets `status=unsubscribed`, flips all `consent_flags` to `False`, stamps `engagement.unsubscribed_at`, returns a styled HTML confirmation page.
- Unsubscribing via an email link is **global** — it revokes email, SMS, and WhatsApp consent simultaneously. There is no per-campaign or per-channel unsubscribe.

#### Bounce Rollup
- On `delivered=False` in `record_delivery_event`, the recipient document is updated: `engagement.bounce_count` and `engagement.delivery_failure_count` are incremented, `engagement.last_bounced_at` is stamped.

#### Engagement Stats (per recipient)
Fields on `recipients.engagement`:
- `open_count_total`, `click_count_total`, `last_open_at`, `last_click_at`
- `bounce_count`, `delivery_failure_count`, `last_bounced_at`
- `unsubscribed_at`
- `tag_scores`, `tag_interaction_counts` — per-tag engagement weights used for dynamic group scoring.

### 7. Recipient & Audience Management
- **Static groups**: `POST /groups/`, `GET /groups/` — fixed list of recipient IDs.
- **Dynamic groups**: Scored by live engagement (`tag_scores`); resolved at queue-preparation time so the audience is always fresh.
- **AI segmentation**: Semantic cosine-similarity across tag embeddings to find recipients from related segments.
- `_channel_ready()` gate: blocks sends to unsubscribed recipients or those who have revoked consent for a channel.

### 8. Analytics

#### Overview (`GET /analytics/overview`)
- Total sent, unique opens/clicks, open rate, click rate, unsubscribe rate.
- 30-day daily trend: opened, clicked, unsubscribed counts per day.
- Top 5 engaged tags (`top_tags`).
- Per-campaign summary rows.

#### Campaign Detail (`GET /analytics/campaigns/{id}`)
- Returns `campaign_name`, `campaign_channels` in addition to metrics.
- Unique opens/clicks, delivery failures, delivery error message, open/click/bounce rates.
- 72-hour hourly timeline.
- Per-recipient activity with status labels (Clicked / Opened / Delivered / Failed).

#### Link Analytics (`GET /analytics/campaigns/{id}/links`)
- Per-URL click totals and unique click counts across a campaign.

#### Recipient History (`GET /analytics/recipients/{id}`)
- Full engagement history for one recipient: campaigns they were in, per-campaign open/click/delivery status.

#### Exports (CSV)
- `GET /analytics/campaigns/{id}/export` — campaign detail CSV (includes Delivery Failures, Unique Opens, Unique Clicks, Delivery Error).
- `GET /analytics/campaigns/{id}/links/export` — link analytics CSV.
- `GET /analytics/overview/export` — all campaigns summary CSV.

### 9. AI Agent & Tools

#### Conversational Agent (`POST /ai/chat`)
- Streaming SSE response (`text/event-stream`).
- Model: `gemini-2.5-flash` (configurable via `MODEL_NAME` in `src/ai/constants.py`). Currently `MAX_TOOL_ITERATIONS = 6`.
- **Thought-signature fix**: Two parallel content lists — `api_contents` (raw proto `Content` objects, preserves `thought_signature`) and `db_contents` (plain dicts for MongoDB). Gemini 3.x/2.5 thinking models require `thought_signature` to be preserved across tool-call turns; stripping it caused a 400 error.
- **Nudge call**: If all iterations produced tool calls but no text, one extra call with an explicit prompt recovers the response.
- **Integrated Tools**:
  - `search_recipients` & `get_recipient_detail`: Look up contacts and their detailed engagement metrics.
  - `list_campaigns` & `get_campaign_detail`: View campaign histories, statuses, and performance.
  - `get_analytics_overview`: Summarize platform-wide performance and top tags.
  - `get_engagement_heatmap`: Aggregate historical open/click data to discover the best times to send emails.
  - `get_campaign_send_performance`: Correlate historical dispatch times with metrics like time-to-first-open.
  - `list_templates`, `get_template_detail`, `create_template`, `update_template`: Full lifecycle management of rich HTML or text message templates.
  - `preview_dynamic_group`, `preview_ai_segmentation`, `list_static_groups`, `create_static_group`: Perform audience exploration and segment building.

#### Smart Segmentation (`preview_ai_segmentation`)
- AI-powered audience segmentation using semantic similarity between tags.
- Discovers recipients from conceptually related existing segments (e.g. matching "developer" with "software-engineer" or "backend") via cosine similarity over tag embeddings.
- Configurable `similarity_threshold` (default `0.15`) balances reach vs precision.
- Can be saved as a static group or dynamic preference seamlessly.

#### Merge Field AI Fill (`POST /ai/fill-merge-fields`)
- Non-streaming single Gemini call.
- Input: `intent` (free text), `campaign_name`, `subject`, `merge_fields[]`.
- Analyzes context and returns `{ values: { field: suggested_value } }` only for the requested dynamic placeholders.
- Heavily utilized by the campaign wizard (Step 3) AI assist panel to automate personalized copy.

#### Spam Detector (`POST /campaigns/check-spam` & Internal)
- Standalone prompt evaluation via Gemini that acts as a highly sensitive spam filter.
- Calculates a floating-point `score` (0.0 to 1.0) based on channel-specific heuristics (email vs SMS vs WhatsApp).
- Flags messages as `is_spam` if the score exceeds `0.7`, providing a qualitative `reason` string.
- Integrated natively into the dispatch queue (blocks sends) and manually accessible in the frontend wizard pre-flight checklist.

### 10. Kafka (Optional Event Bus)
- Topics: `ccirp.campaign.events`, `ccirp.delivery.events`.
- **Gated by `KAFKA_ENABLED` flag** (default `True` in config; set to `False` in `.env` when Kafka is not running). When disabled, `produce_message` returns `False` immediately — librdkafka never starts its background reconnect thread, eliminating log floods.
- All publish functions in `src/events.py` are fail-safe (return `False`, never raise).

### 11. Celery + Redis
- Broker/backend: Redis (`redis://localhost:6379/1`).
- Tasks: `ccirp.dispatch_campaign`, `ccirp.scheduler_tick`, `ccirp.send_reminder`.
- Graceful degradation: if Celery/Redis are unavailable, FastAPI background tasks handle dispatch.

### 12. Email Service
- Provider selected by `EMAIL_PROVIDER` env var: `smtp` (default) or `resend`.
- `MAIL_FROM` must match the authenticated SMTP account (Gmail enforces this). **Do not use Resend's `onboarding@resend.dev` address when `EMAIL_PROVIDER=smtp`.**
- `fast_mail` SMTP client is instantiated at module import time; `.env` changes require a backend restart to take effect.
- Resend provider: JSON HTTP calls to `RESEND_API_BASE_URL/emails` with Bearer auth.

### 13. Tests
- `tests/test_engagement_profiles.py` — 26 async tests across 7 classes covering:
  - `EngagementStats` model defaults and field presence
  - Bounce rollup (`record_delivery_event` when `delivered=False`)
  - Unsubscribe timestamp (`track_unsubscribe`)
  - Plain-text click tracking for SMS/WhatsApp (`_rewrite_plain_text_links`)
  - Link analytics endpoint
  - Recipient history endpoint
  - Unsubscribe rate in analytics overview
- Requires `pytest-asyncio` strict mode (`@pytest.mark.asyncio` on all async tests).
- Mock DB pattern: `_make_db(collections)` with `MagicMock(side_effect=fn)` for `__getitem__`.

---

## Environment Variables Reference

| Variable | Default | Notes |
|---|---|---|
| `MONGODB_URL` | `mongodb://localhost:27017` | |
| `DATABASE_NAME` | `ccirp_db` | |
| `SECRET_KEY` | (change in prod) | JWT signing key |
| `ALGORITHM` | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | 24 h |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | |
| `EMAIL_PROVIDER` | `smtp` | `smtp` or `resend` |
| `SMTP_HOST` | — | e.g. `smtp.gmail.com` |
| `SMTP_PORT` | `587` | |
| `SMTP_USER` | — | Gmail address |
| `SMTP_PASSWORD` | — | App password |
| `MAIL_FROM` | — | Must match `SMTP_USER` for Gmail |
| `SMTP_TLS` | `True` | |
| `SMTP_SSL` | `False` | |
| `RESEND_API_KEY` | — | For Resend provider |
| `RESEND_REPLY_TO` | — | Optional |
| `FRONTEND_URL` | `http://localhost:3000` | CORS origin |
| `TRACKING_BASE_URL` | `http://localhost:8000` | Base for tracking pixel/link URLs |
| `TRACKING_SIGNING_KEY` | (change in prod) | HMAC key for tracking tokens |
| `TRACKING_TOKEN_TTL_SECONDS` | `2592000` | 30 days |
| `GOOGLE_API_KEY` | — | Gemini API key |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/1` | |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | |
| `KAFKA_ENABLED` | `True` | Set `False` when Kafka is not running |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `CAMPAIGN_SCHEDULER_INTERVAL_SECONDS` | `15` | |
| `TWILIO_ACCOUNT_SID` | — | For SMS/WhatsApp |
| `TWILIO_AUTH_TOKEN` | — | |
| `TWILIO_SMS_FROM` | — | |
| `TWILIO_WHATSAPP_FROM` | — | `whatsapp:+1...` format |

---

## Module Layout

```
src/
├── main.py                  # App entry, lifespan, router registration
├── config.py                # All settings (pydantic-settings)
├── database.py              # Motor client (tz_aware=True), get_database()
├── kafka_utils.py           # KafkaManager, topic constants
├── events.py                # publish_campaign_event, publish_delivery_event
├── pagination.py            # PaginatedResponse generic
├── ai/
│   ├── constants.py         # MODEL_NAME, MAX_TOOL_ITERATIONS, SYSTEM_PROMPT
│   ├── router.py            # /ai/chat, /ai/fill-merge-fields, /ai/conversations/*
│   ├── service.py           # agent_stream(), fill_merge_fields()
│   ├── tools.py             # GEMINI_TOOLS definitions + _implementations
│   ├── spam_detector.py     # analyze_spam_score()
│   └── schemas.py           # ChatRequest, FillMergeFieldsRequest, ConversationMeta
├── auth/                    # JWT, bcrypt, OAuth2
├── users/                   # User CRUD
├── templates/               # Template CRUD, preview, test-send, version history
├── communication/
│   ├── router.py            # Campaign CRUD, analytics, retry
│   ├── service.py           # Dispatch pipeline, priority queue, retry_campaign()
│   ├── email_service.py     # SMTP + Resend EmailService
│   ├── messaging_service.py # Per-channel send, html_to_text
│   ├── tracking_router.py   # /track/open, /track/click, /track/unsubscribe
│   ├── tracking_service.py  # record_engagement_event, record_delivery_event (bounce rollup)
│   ├── tracking_utils.py    # inject_click_tracking, unsubscribe footer, pixel tag
│   └── schemas.py / models.py
├── recipients/
│   ├── models.py            # EngagementStats (with bounce_count, unsubscribed_at, etc.)
│   ├── schemas.py           # EngagementStatsSchema
│   └── router.py
├── groups/                  # Static groups, dynamic group preferences, AI segmentation
├── analytics/
│   └── router.py            # Overview, campaign detail, links, recipient history, exports
├── reminders/               # Reminder scheduling (Celery)
└── utils/
    └── tasks.py             # Celery task definitions
```

### 14. Project Documentation
- **Technical Specifications PDF** (`Technical_Specifications.pdf`): A formal, LaTeX-compiled technical specifications document (20 sections, 70+ subsections) covering:
  - System architecture and tech stack
  - Authentication and security (JWT, HMAC tracking tokens)
  - Complete MongoDB data model with field-level descriptions
  - Campaign dispatch pipeline with priority scoring algorithm (full mathematical formulation)
  - Engagement tracking system (open/click/unsubscribe flows)
  - AI-powered features: conversational agent (17 tools), smart segmentation, spam detection, merge-field autocomplete
  - Complete API reference for all route groups
  - Frontend specifications (design system, campaign wizard, template editor, analytics dashboards)
  - Error handling and resilience (graceful degradation matrix)
  - Kafka event bus architecture with message schemas
  - Template engine and versioning pipeline
  - Concurrency model and database index strategy
  - Detailed sequence flows (campaign dispatch, AI agent conversation, engagement tracking)
  - Non-functional requirements (performance, scalability, security, maintainability, observability)
  - Full MongoDB collection glossary and environment variables reference

