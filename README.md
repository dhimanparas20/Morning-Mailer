# Morning Mailer

AI-powered multi-user email summarization system with a FastAPI admin panel. Fetches emails from multiple Gmail accounts, generates AI summaries using LLMs, and delivers them via email (HTML) and/or WhatsApp (plain text) — all managed through a web UI.

## What It Does

Every schedule check (every 5 minutes by default), Morning Mailer:
1. **Checks** each user's scheduled time in Redis (or users.json fallback)
2. **Fetches** emails from Gmail (past N days per user) in parallel
3. **Fetches** Google Calendar events if enabled per user
4. **Categorizes** them: Critical, Important, Informational, or Ignored
5. **Summarizes** using AI into HTML (email) or plain-text (WhatsApp)
6. **Delivers** via SMTP email and/or WhatsApp (WAHA) per user preference

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌─────────────┐
│  Admin Panel │────▶│    Huey      │────▶│  LLM (NVIDIA/
│  (FastAPI)   │     │  (Worker)    │     │  OpenAI/    │
│  Port 8000   │     │              │     │  Groq)       │
└──────────────┘     └──────────────┘     └─────────────┘
       │                     │
       │              ┌──────┴──────┐
       │              │   Redis      │
       │              │  (Valkey)   │
       │              └─────────────┘
       ▼
┌──────────────┐
│    WAHA      │
│  (WhatsApp)  │
│  Port 3000   │
└──────────────┘
```

| Container | Purpose | Does | Does NOT |
|-----------|---------|------|----------|
| `app` | FastAPI admin panel | UI, user CRUD, enqueue huey tasks, OAuth flow | Execute heavy tasks (fetching, LLM, sending) |
| `huey` | Task queue consumer | Process all huey tasks (fetch emails, summarize, send) | Serve UI |
| `valkey` | Redis | Task queue, user storage, scheduling state | - |
| `waha` | WhatsApp API | Send WhatsApp messages | - |

The admin panel **never executes heavy work directly** — it only enqueues huey tasks and returns task IDs.

## Features

- **Multi-User Support**: Add multiple users with separate Gmail accounts
- **Per-User Scheduling**: Each user can have their own schedule_time
- **Per-User Settings**: Customize max_email_results, days_threshold per user
- **Parallel Processing**: Users processed concurrently
- **Smart Fallbacks**: Global .env defaults when per-user settings not specified
- **WhatsApp Integration**: Send summaries via WhatsApp using WAHA
- **Per-Channel Toggle**: Enable/disable email (`use_email`) and WhatsApp (`use_whatsapp`) per user
- **Calendar Integration**: Include Google Calendar events in summaries (`fetch_calendar` per-user toggle)
- **Admin Panel**: Full web UI for managing users, triggering actions, monitoring status
- **OAuth Setup**: Setup Google OAuth tokens through the browser (no CLI needed)
- **Task Queue Architecture**: Admin panel enqueues tasks, huey container executes them asynchronously
- **Bulk Actions**: Select multiple users with checkboxes, trigger email/WhatsApp/revoke in bulk
- **Summary Templates**: Per-user custom prompt for email summarization (stored in Redis)
- **CSV Export**: Download all users as CSV via Users page
- **JSON Import/Export**: Import users by uploading a JSON file, or export current users as JSON download
- **Audit Logs**: Full task-level audit trail stored in Redis (60-day TTL), viewable with search/filter/sort in the Logs admin page
- **Per-User History**: Track email/WhatsApp sends in Redis, viewable per user
- **Token Expiry Alerts**: Badges showing token health (Ready/Expiring/Expired) in users table
- **Job Status Checker**: Paste a task ID to check its status on the dashboard
- **Current Date in Prompts**: All LLM prompts include today's IST date via `{CURRENT_DATE}` placeholder — model never guesses the date

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Gmail OAuth credentials (one `client_secret_web.json` for all users)
- LLM API key (NVIDIA, OpenAI, Groq, or OpenRouter)
- Gmail SMTP credentials for sending emails

### 1. Get Gmail OAuth Credentials
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable **Gmail API** + **Google Calendar API**
3. Create OAuth Client ID → select **Web application**
4. Add authorized JavaScript origin: `http://localhost:8000`
5. Add authorized redirect URI: `http://localhost:8000/oauth/callback`
6. Download JSON → save as `gauth/client_secret_web.json`

### 2. Configure .env
```bash
cp .env.sample .env
```

Key variables:
```bash
# LLM Provider (nvidia/openai/groq/openrouter/google)
MODEL_PROVIDER=openrouter
OPEN_ROUTER_API_KEY=your-api-key

# Scheduler Settings
SCHEDULE_TIME=08:00
DAYS_THRESHOLD=2
MAX_EMAIL_RESULTS=20

# Email Settings (fallback for users without custom SMTP)
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

# Redis
REDIS_URL=redis://:testpass@valkey:6379/0

# Admin Panel
ADMIN_USERNAME=admin
ADMIN_PASSWORD=changeme
SECRET_KEY=change-this-to-a-random-secret-key
ADMIN_PORT=8000

# WhatsApp (WAHA)
WAHA_API_URL=http://waha:3000
WAHA_API_KEY=your-waha-api-key
```

### 3. Configure Users

Users are stored in **Redis** (Valkey) as hashes at `USERS_CONFIG:<keyword>`.

#### Option A: Admin Panel (recommended)
1. Start the stack: `docker compose up -d`
2. Open http://localhost:8000
3. Login with admin/changeme
4. Add users via the UI

#### Option B: CLI
```bash
python cli_users.py add --name "Paras" --email "paras@gmail.com" --keyword dhimanparas20
python cli_users.py list
python cli_users.py update dhimanparas20 --schedule-time "09:00"
```

#### Option C: IPython magics
```bash
docker compose exec huey uv run ipython
%redis_users_add --name "Paras" --email "paras@gmail.com" --keyword dhimanparas20
%redis_users_list
```

#### Option D: users.json (fallback)
If no users are found in Redis, the system falls back to `users.json`.

**User Fields:**
| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | Yes | - | Display name |
| `email` | Yes | - | Where to send summary |
| `keyword` | Yes | - | Links to token_<keyword>.json |
| `active` | No | true | If false, user is skipped |
| `use_email` | No | true | Enable/disable email delivery |
| `use_whatsapp` | No | true | Enable/disable WhatsApp delivery |
| `fetch_calendar` | No | false | Include Google Calendar events |
| `max_email_results` | No | .env default | Max emails to fetch |
| `days_threshold` | No | .env default | Days to look back |
| `schedule_time` | No | .env SCHEDULE_TIME | When to run (HH:MM) |
| `smtp_host_user` | No | .env EMAIL_HOST_USER | Custom SMTP sender |
| `smtp_host_password` | No | .env EMAIL_HOST_PASSWORD | Custom SMTP password |
| `mobile` | No | - | WhatsApp number (country code, no +) |
| `summary_template` | No | (empty = default) | Custom prompt for email summarization |

### 4. First-Time OAuth Setup

Each user needs an OAuth token for Gmail/Calendar access.

#### Option A: Desktop OAuth (local machine)
```bash
uv run python -m modules.fetch_emails setup <keyword>
```

#### Option B: Web OAuth (via admin panel)
1. Open http://localhost:8000/users
2. Click the "Setup" button next to a user without a token
3. Complete Google OAuth flow — token is saved automatically

#### Option C: IPython
```bash
docker compose exec huey uv run ipython
%setup_oauth <keyword>
%check_tokens
```

### 5. Run
```bash
# Start everything
docker compose up -d

# Check admin panel logs
docker compose logs -f app

# Check huey worker logs
docker compose logs -f huey

# Access admin panel
open http://localhost:8000
```

## Project Structure

```
Morning-Mailer/
├── tasks.py                    # Huey tasks & scheduling logic
├── admin/                      # FastAPI admin panel
│   ├── main.py                 # App entry point
│   ├── config.py               # Settings from .env
│   ├── auth.py                 # Session auth + CSRF + AuthMiddleware
│   ├── models.py               # Pydantic models
│   ├── services.py             # Business logic (enqueues huey tasks, bulk actions, history, CSV export)
│   ├── routes/
│   │   ├── auth_routes.py      # Login/logout
│   │   ├── user_routes.py      # User CRUD, CSV export, token revoke, summary template handling
│   │   ├── action_routes.py    # Trigger actions (email/whatsapp/calendar), bulk endpoints, history, calendar fetch modal
│   │   ├── oauth_routes.py     # OAuth flow (/callback BEFORE /{keyword})
│   │   └── system_routes.py    # Redis/scheduler status
│   ├── templates/              # Jinja2 HTML templates
│   │   ├── base.html           # Base layout (glassmorphism, navbar/scripts blocks)
│   │   ├── login.html          # Login page (no navbar)
│   │   ├── dashboard.html      # Dashboard with stats/actions
│   │   ├── users.html          # User list with search/sort, bulk selection, token badges, history, OAuth Setup/Copy buttons
│   │   ├── user_form.html      # Add/edit form (checkbox JS fix, SMTP placeholders, summary template)
│   │   ├── oauth_redirect.html # Redirects to Google OAuth (uses | safe filter)
│   │   ├── oauth_result.html   # OAuth success/failure result
│   │   └── audit_log.html      # Audit log viewer with search/filter/sort/pagination
│   └── static/
│       ├── css/style.css       # Purple gradient glassmorphism theme
│       └── js/app.js           # Toast notifications, task ID copy, bulk selection, history/calendar modals, job status checker
├── modules/
│   ├── fetch_emails.py         # Gmail API (keyword-based tokens)
│   ├── fetch_calendar.py       # Google Calendar API (shares tokens with Gmail)
│   ├── agent_mod.py            # LLM wrapper (summarize_emails)
│   ├── agent_utils.py          # LLM factory (MODEL_REGISTRY)
│   ├── prompt.py               # Prompt templates (email + WhatsApp + calendar)
│   ├── logger.py               # Logging (get_logger)
│   ├── generics.py             # Utilities
│   ├── redis_users.py          # Redis user storage & CRUD
│   ├── web_auth.py             # Web OAuth (get_auth_url, exchange_code_for_token)
│   └── ipython_startup.py      # IPython magic functions
├── cli_users.py                # CLI for Redis user management
├── gauth/                      # OAuth credentials
│   ├── client_secret.json      # Desktop OAuth (legacy)
│   ├── client_secret_web.json  # Web OAuth (recommended)
│   └── tokens/                 # One token per user
│       └── token_<keyword>.json
├── users.json                  # User definitions (fallback)
├── users.json.sample           # User template
├── .env                        # Configuration
├── .env.sample                 # Environment template
├── Dockerfile                  # Container image
├── compose.yml                 # Docker orchestration (4 services)
├── pyproject.toml              # Dependencies
├── README.md                   # This file
└── AGENTS.md                   # LLM-facing codebase docs
```

## Docker Services

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| `app` | `app` | 8000 | FastAPI admin panel |
| `huey` | `huey` | - | Task queue consumer |
| `valkey` | `valkey` | 6379 | Redis (task queue + user storage) |
| `waha` | `waha` | 3000 | WhatsApp HTTP API |

### Starting Services
```bash
# Start all
docker compose up -d

# Start specific service
docker compose up -d app

# Rebuild and start
docker compose up -d --build

# Stop all
docker compose down
```

### Checking Logs
```bash
# Admin panel
docker compose logs -f app

# Huey worker
docker compose logs -f huey

# All services
docker compose logs -f
```

## Admin Panel

Access at http://localhost:8000 (default: admin/changeme)

### Features
- **Dashboard**: Stats cards, quick actions, scheduler config, job status checker, users overview with last run times
- **Users**: Full CRUD with search/sort/filter, per-user action buttons, OAuth Setup + Revoke + Copy buttons, token expiry badges (Ready/Expiring/Expired), history button, bulk selection checkboxes
- **Bulk Actions**: Select multiple users → trigger email/WhatsApp/revoke tokens for all selected
- **Summary Templates**: Per-user custom prompt textarea in edit form, stored in Redis
- **Import/Export**: Import users by uploading a JSON file (Users page → Import), or download as JSON or CSV
- **Actions**: Trigger email/whatsapp summaries, force all, test send, calendar fetch — returns task ID with copy button
- **Audit Logs**: Browse all task executions with filtering by task type, keyword, status, and free-text search. Pagination and auto-refresh included
- **Job Status**: Paste a task ID to check its status (pending/finished/error)
- **OAuth**: Setup OAuth tokens through the browser (click "Setup" → authorize → done)
- **System**: Redis status, model switching, last-run clearing

### Architecture
The admin panel enqueues huey tasks via Redis. The huey container picks them up and executes. This means:
- Admin panel responds immediately with a task ID + copy button
- Actual work happens asynchronously in the huey container
- Users can check status manually via "Check Job Status" on dashboard
- Edit user form redirects back to form with success toast (not JSON)

## Configuration

### .env Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MODEL_PROVIDER` | LLM: nvidia/openai/groq/openrouter/google | openrouter |
| `MODEL_TEMPERATURE` | AI creativity (0-2) | 0.5 |
| `MAX_TOKENS` | Max response length | 10500 |
| `REDIS_URL` | Valkey Redis connection string | - |
| `SCHEDULE_TIME` | Default run time (HH:MM) | 08:00 |
| `DAYS_THRESHOLD` | Default days to look back | 2 |
| `MAX_EMAIL_RESULTS` | Default max emails to fetch | 20 |
| `MAX_THREAD_WORKERS` | Parallel users | 5 |
| `SCHEDULE_CHECK_INTERVAL` | Minutes between checks | 5 |
| `RETRY_COUNT` | Retry attempts | 2 |
| `RETRY_DELAY` | Seconds between retries | 60 |
| `ENV_MODE` | dev/prod mode | dev |
| `EMAIL_HOST_USER` | SMTP fallback username | - |
| `EMAIL_HOST_PASSWORD` | SMTP fallback password | - |
| `OAUTH_CALLBACK_URL` | OAuth callback URL (must end with `/oauth/callback`, NOT just `/callback`) | http://localhost:8000/oauth/callback |
| `WAHA_API_URL` | WAHA server URL | http://waha:3000 |
| `WAHA_API_KEY` | WAHA API key | - |
| `WAHA_SESSION` | WAHA session name | default |
| `ADMIN_USERNAME` | Admin panel username | admin |
| `ADMIN_PASSWORD` | Admin panel password | changeme |
| `SECRET_KEY` | Session secret key | - |
| `ADMIN_PORT` | Admin panel port | 8000 |

### Scheduling

- Task runs every `SCHEDULE_CHECK_INTERVAL` minutes (default: 5)
- For each user, checks if current time >= user's schedule_time
- If yes and hasn't run today → processes that user in parallel
- Users without schedule_time use global SCHEDULE_TIME from .env

### Environment Modes (`ENV_MODE`)

| Mode | Run Frequency | Log Level | Description |
|------|--------------|-----------|-------------|
| `dev` | Multiple times/day | DEBUG | Skips Redis last_run check, verbose logs |
| `prod` | Once per day only | SUCCESS | Enforces Redis last_run check, minimal logs |

## WhatsApp Setup (WAHA)

Morning Mailer uses [WAHA](https://waha.devlike.pro) (WhatsApp HTTP API) to send WhatsApp messages.

1. **Start WAHA**: `docker compose up -d waha`
2. **Open dashboard**: http://localhost:3000/dashboard
3. **Scan QR code** with WhatsApp on your phone
4. **Configure .env** with WAHA credentials
5. **Add `mobile`** field to users

## Manual Testing

```bash
# Trigger daily summary
docker compose exec huey python -c "from tasks import daily_summary; daily_summary()"

# Test email sending
docker compose exec huey python -c "from tasks import send_email; send_email('test@example.com', 'Test', 'Hello')"

# Check Redis status
docker compose exec huey python -c "import redis; r = redis.from_url('redis://:testpass@valkey:6379/0'); print(r.ping())"
```

## Troubleshooting

### Admin panel not loading
```bash
docker compose logs app
docker compose restart app
```

### Huey not processing tasks
```bash
docker compose logs huey
docker compose restart huey
```

### Gmail credentials not found
- Ensure `gauth/client_secret_web.json` exists
- Ensure `gauth/tokens/token_<keyword>.json` exists for each user

### Email sending fails
- Check `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` in `.env`
- Use Gmail App Password (not your regular password)

### OAuth token not found
```bash
# Generate new token via admin panel: http://localhost:8000/users
# Or via CLI:
uv run python -m modules.fetch_emails setup <keyword>
```

### OAuth scope error (403 insufficient permissions)
- Token was generated without proper scopes — re-authorize via admin panel Setup button
- Or delete the token and regenerate: `rm gauth/tokens/token_<keyword>.json` then Setup again

### OAuth callback fails
- Ensure `OAUTH_CALLBACK_URL` in `.env` matches the port your admin panel is on
- The callback URL **must** end with `/oauth/callback` (the full route is prefix `/oauth` + path `/callback`). A URL ending in just `/callback` will be intercepted by `AuthMiddleware` and redirected to `/login`.
- Ensure Google Cloud Console redirect URI matches exactly: `http://localhost:8000/oauth/callback`
- Ensure Google Cloud Console JS origin includes: `http://localhost:8000`

## Tech Stack

- **Task Queue**: Huey (Redis-backed)
- **Admin Panel**: FastAPI + Jinja2 + Bootstrap 5
- **Gmail API**: google-api-python-client
- **Calendar API**: google-api-python-client
- **LLM**: LangChain (NVIDIA, OpenAI, Groq, OpenRouter, Google)
- **Logging**: loguru
- **Email**: smtplib (SMTP)
- **WhatsApp**: WAHA (WhatsApp HTTP API)
- **Container**: Docker + Docker Compose

## License

MIT
