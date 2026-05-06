# CCIRP Backend

## Overview

The **CCIRP Backend** powers the **Central Communication and Intelligent Reminder Platform** — a multi-channel communication system for email, SMS, and WhatsApp campaigns. Built on FastAPI with an async-first architecture.

---

## Tech Stack

| Component | Technology |
|---|---|
| API Framework | FastAPI (async) |
| Database | MongoDB via Motor (`tz_aware=True`) |
| Auth | JWT (access 24 h + refresh 7 d), bcrypt |
| Email | fastapi-mail (SMTP) + Resend API |
| SMS / WhatsApp | Twilio |
| Background Tasks | Celery + Redis (graceful fallback to FastAPI BackgroundTasks) |
| Event Bus | Kafka via confluent-kafka (optional, gated by `KAFKA_ENABLED`) |
| AI | Google Gemini via `google-generativeai` SDK |
| Task Queue | Internal async priority queue in MongoDB |
| Testing | pytest + pytest-asyncio (strict mode) |

---

## Project Structure

```
src/
├── main.py                  # App entry, lifespan, CORS
├── config.py                # All env-var settings (pydantic-settings)
├── database.py              # Motor client (tz_aware=True)
├── kafka_utils.py / events.py  # Optional Kafka event publishing
├── ai/                      # Gemini agent, merge-field fill, spam detector
├── auth/                    # JWT, bcrypt, OAuth2
├── users/                   # User CRUD
├── templates/               # Template CRUD, preview, test-send, versioning
├── communication/           # Campaign engine, dispatch, tracking, email/SMS/WA
├── recipients/              # Recipient CRUD, engagement stats
├── groups/                  # Static groups, dynamic groups, AI segmentation
├── analytics/               # Overview, campaign detail, links, exports
├── reminders/               # Reminder scheduling
└── utils/                   # Celery tasks
```

---

## Installation

```bash
cd CCIRP-be
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements/base.txt
```

For development:
```bash
pip install -r requirements/dev.txt
```

---

## Running

```bash
uvicorn src.main:app --reload
```

API available at `http://127.0.0.1:8000`. Docs at `/docs` (Swagger) and `/redoc`.

Optional workers (only if Redis and Celery are available):
```bash
celery -A src.celery_app worker --loglevel=info
celery -A src.celery_app beat --loglevel=info
```

---

## Environment Variables

Create `.env` in `CCIRP-be/`:

```env
# MongoDB
MONGODB_URL=mongodb+srv://...
DATABASE_NAME=ccirp_db

# Auth
SECRET_KEY=change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
REFRESH_TOKEN_EXPIRE_DAYS=7

# Email — MAIL_FROM must match SMTP_USER for Gmail
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-app-password
MAIL_FROM=you@gmail.com
SMTP_TLS=True
SMTP_SSL=False

# Resend (alternative email provider)
RESEND_API_KEY=re_...
RESEND_API_BASE_URL=https://api.resend.com
RESEND_REPLY_TO=you@gmail.com

# SMS / WhatsApp
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_SMS_FROM=+1...
TWILIO_WHATSAPP_FROM=whatsapp:+1...
TWILIO_API_BASE_URL=https://api.twilio.com

# Tracking
FRONTEND_URL=http://localhost:3000
TRACKING_BASE_URL=http://localhost:8000
TRACKING_SIGNING_KEY=change-in-production
TRACKING_TOKEN_TTL_SECONDS=2592000

# AI
GOOGLE_API_KEY=AIza...

# Celery / Redis
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/1
REDIS_URL=redis://localhost:6379/0

# Kafka — set False if Kafka is not running (prevents log floods)
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_ENABLED=False

# Scheduler
CAMPAIGN_SCHEDULER_INTERVAL_SECONDS=15
```

---

## Key API Endpoints

### Auth
| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Register user |
| POST | `/auth/login` | Login, receive tokens |
| POST | `/auth/refresh` | Refresh access token |
| GET | `/auth/me` | Current user |

### Templates
| Method | Path | Description |
|---|---|---|
| GET | `/templates/` | List all |
| POST | `/templates/` | Create |
| PUT | `/templates/{id}` | Update (archives version) |
| DELETE | `/templates/{id}` | Delete |
| POST | `/templates/preview` | Render with sample data |
| POST | `/templates/{id}/test-send` | Send real email |

### Campaigns
| Method | Path | Description |
|---|---|---|
| GET | `/campaigns/` | List campaigns |
| POST | `/campaigns/` | Create + enqueue |
| GET | `/campaigns/{id}` | Get campaign |
| GET | `/campaigns/{id}/analytics` | Full analytics |
| POST | `/campaigns/{id}/retry` | Retry failed/partially_sent |
| POST | `/campaigns/check-spam` | Spam pre-check |

### Analytics
| Method | Path | Description |
|---|---|---|
| GET | `/analytics/overview` | Platform-wide stats + trend |
| GET | `/analytics/overview/export` | CSV of all campaigns |
| GET | `/analytics/campaigns/{id}` | Campaign detail |
| GET | `/analytics/campaigns/{id}/links` | Link click stats |
| GET | `/analytics/campaigns/{id}/export` | Campaign CSV |
| GET | `/analytics/campaigns/{id}/links/export` | Links CSV |
| GET | `/analytics/recipients/{id}` | Recipient history |

### Tracking (public, no auth)
| Method | Path | Description |
|---|---|---|
| GET | `/track/open/{token}.png` | Open pixel (email only) |
| GET | `/track/click/{token}` | Click redirect |
| GET | `/track/unsubscribe/{token}` | Global opt-out |

### AI
| Method | Path | Description |
|---|---|---|
| POST | `/ai/chat` | Streaming SSE agent |
| POST | `/ai/fill-merge-fields` | AI merge field suggestions |
| GET | `/ai/conversations` | List conversations |
| GET | `/ai/conversations/{id}` | Get conversation |
| DELETE | `/ai/conversations/{id}` | Delete conversation |

### AI Tools & Capabilities

The backend features a robust suite of AI capabilities powered by Google Gemini:

1. **Conversational Agent (`/ai/chat`)**
   - A streaming assistant built on `gemini-2.5-flash` with access to the platform's data.
   - Capable of managing campaigns, querying analytics, exploring recipient engagement, and manipulating templates or groups.
   - Retains context across tool iterations by preserving the `thought_signature`.

2. **Smart Segmentation & Dynamic Groups**
   - **Semantic Tag Matching**: Uses cosine similarity to find recipients with tags semantically related to a target segment, automatically broadening audience reach for relevant users.
   - **Dynamic Ranking**: Ranks recipients by live engagement scores based on tag interactions, resolving the top-K members at dispatch time.

3. **Pre-flight Spam Detection**
   - Evaluates campaign subject and body content using an AI-driven filter tuned specifically for email, SMS, or WhatsApp.
   - Calculates a spam score (0.0 to 1.0) and enforces a threshold (>= 0.7) to block campaigns before dispatch, providing a detailed explanation for its decision.

4. **AI Merge Field Autocomplete**
   - Analyzes campaign context (name, subject, intent description) to generate highly contextual values for custom merge fields (e.g. `{{promo_code}}`, `{{closing}}`) in the template.

5. **Advanced Analytics Tools**
   - **Engagement Heatmap**: Aggregates all open and click events across campaigns by hour-of-day and day-of-week (UTC) to recommend optimal send times.
   - **Send Performance**: Correlates historical campaign send times with open rates, click rates, and time-to-first-open.

---

### Recipients / Groups
| Method | Path | Description |
|---|---|---|
| GET/POST | `/recipients/` | List / create |
| GET/PUT/DELETE | `/recipients/{id}` | CRUD |
| GET/POST | `/groups/` | Static groups |
| GET | `/groups/dynamic-preferences` | Saved dynamic configs |
| POST | `/groups/resolve-dynamic` | Resolve live audience |
| POST | `/groups/segmentation` | AI semantic segmentation |

---

## Important Implementation Notes

- **Motor `tz_aware=True`**: All datetimes from MongoDB are UTC-aware. Without this, naive datetimes serialize without a timezone offset and the browser misinterprets them as local time.
- **SMTP `MAIL_FROM`**: Must match the authenticated Gmail account. Setting it to any other address (e.g. `onboarding@resend.dev`) causes Gmail to reject the send. Changes require a backend restart since `fast_mail` is built at import time.
- **Kafka `KAFKA_ENABLED=False`**: Set this when Kafka is not running. Without it, librdkafka's background thread retries the broker connection every 30 s and floods stderr.
- **Gemini thought_signature**: When using thinking models (2.5 Flash, 3.x), function call parts carry a `thought_signature` that must be preserved across tool-call iterations. The agent uses `api_contents` (raw proto objects) for API calls and `db_contents` (plain dicts) for MongoDB storage to avoid stripping this field.
- **Campaign retry**: Only resets `failed`/`cancelled` queue entries — already-completed sends are not re-sent. The retry endpoint returns 409 for any status other than `failed` or `partially_sent`.

---

## Authors

Group 6 — Software Engineering Project, IITH

- CS23BTECH11007 Arnav Maiti
- CS23BTECH11009 Bhumin Hirpara
- CS23BTECH11023 Karan Gupta
- CS23BTECH11048 Pranjal Prajapati
- CS23BTECH11052 Roshan Y Singh
- CS23BTECH11060 Sujal Meshram

*Academic and research use only.*
