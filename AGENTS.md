# Morning Mailer - Codebase Documentation for AI Agents

## Project Overview

Morning Mailer is an AI-powered **multi-user** email summarization system with a **FastAPI admin panel**. It automatically fetches emails from multiple Gmail accounts at scheduled times, generates summaries using Large Language Models, and delivers them via email (HTML) and/or WhatsApp (plain text) to each user.

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

### Container Responsibilities

| Container | Purpose | Does | Does NOT |
|-----------|---------|------|----------|
| `app` | FastAPI admin panel | UI, user CRUD, enqueue huey tasks, OAuth flow | Execute heavy tasks (fetching, LLM, sending) |
| `huey` | Task queue consumer | Process all huey tasks (fetch emails, summarize, send) | Serve UI |
| `valkey` | Redis | Task queue, user storage, scheduling state | - |
| `waha` | WhatsApp API | Send WhatsApp messages | - |

### Key Architecture Decision

The admin panel (`app`) **never executes heavy work directly**. When a user clicks "Send Email Summary":
1. Admin panel calls `services.run_send_email_summary(keyword)`
2. This calls `tasks.huey_send_email_to_user(keyword)` — a `@huey.task` decorated function
3. Huey enqueues the task to Redis and returns a `TaskWrapper`
4. Admin panel returns `task_id` to the frontend
5. Huey container picks up the task and executes it
6. Frontend polls `/actions/status/{task_id}` for completion

## Core Components

### 1. tasks.py - Huey Tasks & Scheduling
- **Purpose**: Defines all huey tasks and scheduling logic
- **Key Pattern**: LLM agent is **lazy-initialized** — `AGENT = None` at module level, `get_agent()` initializes on first use. This prevents the app container (admin panel) from loading the LLM when it only needs to import task functions.
- **Key Functions**:
  - `get_agent()`: Lazy-initializes LLM (only in huey container, never in app)
  - `load_users()`: Loads active users from Redis first, falls back to users.json
  - `get_user_settings(user)`: Gets per-user max_email_results & days_threshold
  - `should_run_today(user, global_schedule_time, redis_prefix="")`: Checks if user's schedule time has passed today
  - `fetch_emails_with_retry(keyword, max_results, days_threshold)`: Fetches with retry logic
  - `fetch_calendar_events_with_retry(keyword, days, max_results)`: Calendar fetch with retry
  - `process_user(user, global_schedule_time)`: Full pipeline for one user (email)
  - `send_email(to, subject, body, is_html, smtp_user, smtp_password)`: Sends via SMTP
  - `send_whatsapp(mobile, text)`: Sends WhatsApp via WAHA API

- **Huey Tasks (enqueued by admin panel)**:
  - `huey_send_email_to_user(keyword)`: Fetch, summarize, send email to one user
  - `huey_send_whatsapp_to_user(keyword)`: Fetch, summarize, send WhatsApp to one user
  - `huey_force_email_all()`: Force email for ALL users
  - `huey_force_whatsapp_all()`: Force WhatsApp for ALL users
  - `huey_fetch_calendar_and_send_email(keyword, days)`: Calendar → email
  - `huey_fetch_calendar_and_send_whatsapp(keyword, days)`: Calendar → WhatsApp
  - `huey_fetch_calendar_and_send_both(keyword, days)`: Calendar → both
  - `huey_test_send_email(subject, body)`: Test email
  - `huey_test_send_whatsapp(mobile, message)`: Test WhatsApp

- **Periodic Tasks**:
  - `daily_summary()`: Unified task — checks all users, processes email and/or WhatsApp per user preference. Also prints startup summary on first run (guarded by `_startup_summary_printed` flag).

- **Scheduling Logic**:
  - Task runs every N minutes (SCHEDULE_CHECK_INTERVAL, default: 5)
  - For each user, checks if current time >= user's schedule_time
  - Email tracking key: `morning_mailer:last_run:<keyword>`
  - WhatsApp tracking key: `morning_mailer:whatsapp_last_run:<keyword>`

### 2. admin/ - FastAPI Admin Panel

#### 2.1 admin/main.py - App Entry
- Creates FastAPI app with middleware, static files, templates
- Mounts all routers
- Serves dashboard at `/`

#### 2.2 admin/config.py - Settings
- Pydantic Settings loaded from `.env`
- Key settings: `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`, `REDIS_URL`

#### 2.3 admin/auth.py - Authentication
- Session-based auth (not JWT)
- CSRF protection via double-submit cookie
- `AuthMiddleware` intercepts requests, checks session
- Login/logout endpoints

#### 2.4 admin/models.py - Pydantic Models
- `UserCreate`, `UserUpdate` — user form validation
- `ActionRequest`, `ModelSwitchRequest` — action form validation

#### 2.5 admin/services.py - Business Logic
- **Purpose**: Thin layer between routes and tasks module
- **Key Pattern**: All action functions call `tasks.huey_*()` which enqueues to huey
- **Key Functions**:
  - `list_users()`, `get_user()`, `create_user()`, etc. — User CRUD (Redis or users.json fallback)
  - `run_send_email_summary(keyword)` → enqueues `huey_send_email_to_user`
  - `run_send_whatsapp_summary(keyword)` → enqueues `huey_send_whatsapp_to_user`
  - `run_force_email_summary()` → enqueues `huey_force_email_all`
  - `check_task_status(task_id)` — polls huey for task result
  - `get_redis_status()` — Redis connection info
  - `get_scheduler_status()` — Scheduler config from tasks module
  - `generate_oauth_url(keyword)` — Creates Google OAuth URL
  - `exchange_oauth_code(code, keyword)` — Exchanges auth code for token
- **Note**: Tasks module is imported once at startup (no `importlib.reload`) to avoid re-initializing module-level code in the app container.

#### 2.6 admin/routes/ - API Routes

| Router | Prefix | Purpose |
|--------|--------|---------|
| `auth_routes` | `/login`, `/logout` | Login/logout with CSRF |
| `user_routes` | `/users` | User CRUD, search/sort, import/export |
| `action_routes` | `/actions` | Trigger email/whatsapp/calendar actions, test send, model switch |
| `oauth_routes` | `/oauth` | OAuth start + callback |
| `system_routes` | `/` | Redis status, scheduler status, tokens status |

#### 2.7 admin/templates/ - Jinja2 Templates

| Template | Purpose |
|----------|---------|
| `base.html` | Base layout (navbar, Bootstrap 5, glassmorphism theme) |
| `login.html` | Login page (no navbar, centered card) |
| `dashboard.html` | Stats cards, quick actions, scheduler config, users overview |
| `users.html` | User list with search/sort/filter, action buttons |
| `user_form.html` | Add/edit user form |
| `oauth_redirect.html` | Redirects to Google OAuth |
| `oauth_result.html` | Shows OAuth success/failure |

#### 2.8 admin/static/ - Static Files
- `css/style.css` — Purple gradient glassmorphism theme
- `js/app.js` — Toast notifications, action handlers, task status polling

### 3. modules/fetch_emails.py - Gmail Integration
- **Purpose**: Handles all Gmail API interactions
- **Key Functions**:
  - `get_gmail_service(keyword)`: Initializes Gmail API client with OAuth
  - `fetch_emails(keyword, max_results, query, date_from, date_to, ...)`: Main API
  - `get_token_path(keyword)`: Returns path to token_<keyword>.json
  - `get_credentials_path()`: Returns path to client_secret.json

- **OAuth Structure** (SINGLE SECRET, MULTIPLE TOKENS):
  ```
  gauth/
  ├── client_secret.json         ← Desktop OAuth app (legacy)
  ├── client_secret_web.json     ← Web OAuth app (recommended)
  └── tokens/
      ├── token_dhimanparas20.json  ← User 1's token
      ├── token_bobyHP07.json       ← User 2's token
      └── ...
  ```

### 4. modules/web_auth.py - Web OAuth Setup
- Handles OAuth flow for web/remote setups
- Uses itcyou tunnel for callback URL
- Exchanges authorization code for token

### 5. modules/fetch_calendar.py - Google Calendar Integration
- **Purpose**: Handles all Google Calendar API interactions
- **Key Functions**:
  - `get_calendar_service(keyword)`: Initializes Calendar API client
  - `fetch_events(keyword, calendar_id, time_min, time_max, max_results, ...)`: Full event fetcher
  - `fetch_upcoming_events(keyword, days, max_results)`: Convenience for next N days
  - `has_valid_token(keyword)`: Checks if OAuth token exists
- **Token Sharing**: Uses the same `token_<keyword>.json` as Gmail
- **OAuth Scope**: Requires `calendar.readonly`

### 6. modules/redis_users.py - Redis User Storage
- **Purpose**: Store and manage users as Redis hashes
- **Key Pattern**: `USERS_CONFIG:<keyword>` — each user is a Redis hash
- **Key Methods**:
  - `add_or_update(user_dict)`: Insert or replace a user hash
  - `get(keyword)`: HGETALL → typed Python dict
  - `get_all()`: SMEMBERS + pipelined HGETALL → list of dicts
  - `delete(keyword)`: Remove hash + keyword from index set
  - `activate(keyword)` / `deactivate(keyword)`: Toggle active field
  - `import_from_json(path)`: Bulk-import from users.json
  - `export_to_json(path)`: Bulk-export to users.json
  - `clear_all()`: Delete all users from Redis
  - `count()` / `exists(keyword)`: Cardinality checkers
- **Type Handling**: Bools stored as `1`/`0`, ints as strings, rehydrated on read

### 7. modules/agent_mod.py - LLM Integration
- **Purpose**: Wrapper for LLM summarization
- **Key Functions**:
  - `init()`: Initializes LLM from config (MODEL_PROVIDER)
  - `summarize_emails(emails, prompt)`: Generates HTML summary
  - `hot_switch_model(provider, model_name, temperature)`: Hot-swap LLM at runtime
- **Supported Providers**: nvidia, openai, groq, openrouter, google

### 8. modules/prompt.py - Prompt Templates
- **Variables**:
  - `EMAIL_SYSTEM_PROMPT`: HTML summary format with inline CSS
  - `WHATSAPP_SYSTEM_PROMPT`: Plain-text WhatsApp format with *bold*, _italic_, emoji markers
  - `CALENDAR_EMAIL_PROMPT`: Calendar events → HTML email format
  - `CALENDAR_WHATSAPP_PROMPT`: Calendar events → WhatsApp format
  - `SYSTEM_PROMPT`: Backward-compat alias for EMAIL_SYSTEM_PROMPT

### 9. modules/ipython_startup.py - Magic Functions
- Available in IPython inside the huey container
- Provides `%daily_email_summary`, `%send_email_summary <keyword>`, etc.

## File Structure

```
Morning-Mailer/
├── tasks.py                    # Huey tasks & scheduling
├── admin/                      # FastAPI admin panel
│   ├── main.py                 # App entry point
│   ├── config.py               # Settings from .env
│   ├── auth.py                 # Session auth + CSRF
│   ├── models.py               # Pydantic models
│   ├── services.py             # Business logic (enqueues huey tasks)
│   ├── routes/
│   │   ├── auth_routes.py      # Login/logout
│   │   ├── user_routes.py      # User CRUD
│   │   ├── action_routes.py    # Trigger actions
│   │   ├── oauth_routes.py     # OAuth flow
│   │   └── system_routes.py    # Redis/scheduler status
│   ├── templates/              # Jinja2 HTML templates
│   └── static/                 # CSS + JS
├── modules/
│   ├── fetch_emails.py         # Gmail API
│   ├── fetch_calendar.py       # Google Calendar API
│   ├── agent_mod.py            # LLM wrapper
│   ├── agent_utils.py          # LLM factory
│   ├── prompt.py               # Prompt templates
│   ├── logger.py               # Logging
│   ├── generics.py             # Utilities
│   ├── redis_users.py          # Redis user storage
│   ├── web_auth.py             # Web OAuth setup
│   └── ipython_startup.py      # IPython magics
├── cli_users.py                # CLI for Redis user management
├── gauth/
│   ├── client_secret.json      # Desktop OAuth (shared)
│   ├── client_secret_web.json  # Web OAuth (shared)
│   └── tokens/                 # One token per user
├── users.json                  # User definitions (fallback)
├── .env                        # Configuration
├── Dockerfile                  # Container image
├── compose.yml                 # Docker orchestration
└── pyproject.toml              # Dependencies
```

## Running Commands

### Docker Compose
```bash
# Start all services
docker compose up -d

# Start specific service
docker compose up -d app
docker compose up -d huey

# Rebuild and start
docker compose up -d --build

# Stop all
docker compose down

# Check logs
docker compose logs -f app      # Admin panel
docker compose logs -f huey     # Task worker
docker compose logs -f          # All services
```

### Admin Panel
```bash
# Access
open http://localhost:8000

# Default credentials
Username: admin
Password: changeme

# Rebuild admin panel only
docker compose up -d --build app
```

### CLI Tools
```bash
# User management
python cli_users.py list
python cli_users.py add --name "Name" --email "email@gmail.com" --keyword myname
python cli_users.py update myname --schedule-time "09:00"
python cli_users.py remove myname

# OAuth setup
uv run python -m modules.fetch_emails setup <keyword>
uv run python -m modules.fetch_emails check

# Web OAuth
uv run python -m modules.web_auth <keyword>
```

### IPython (inside huey container)
```bash
docker compose exec huey uv run ipython

# Available magics:
%daily_email_summary
%send_email_summary <keyword>
%send_whatsapp_summary <keyword>
%force_email_summary
%force_whatsapp_summary
%setup_oauth <keyword>
%check_tokens
%fetch_calendar <keyword> [days]
%redis_status
%redis_users_list
%clear_last_run [keyword|all]
```

### Direct Python (inside huey container)
```bash
docker compose exec huey python -c "from tasks import daily_summary; daily_summary()"
docker compose exec huey python -c "from tasks import send_email; send_email('test@example.com', 'Test', 'Hello')"
```

## Data Flow

```
1. Huey scheduler triggers every SCHEDULE_CHECK_INTERVAL minutes
           │
           ▼
2. daily_summary() called
           │
           ▼
3. For each active user in Redis:
    ├── Check if current time >= user's schedule_time
    ├── Check use_email / use_whatsapp per-user booleans
    └── If eligible → add to eligible_users
           │
           ▼
4. Eligible users processed in parallel (ThreadPoolExecutor)
           │
           ▼
5. For each eligible user:
    ├── Fetch emails (fetch_emails_with_retry)
    ├── Fetch calendar events if fetch_calendar=true
    ├── Summarize with LLM (email or WhatsApp prompt)
    ├── Send via enabled channels
    └── Update Redis last_run tracking
```

### Admin Panel Action Flow
```
1. User clicks "Send Email" in admin panel
           │
           ▼
2. POST /actions/email/send/{keyword}
           │
           ▼
3. services.run_send_email_summary(keyword)
           │
           ▼
4. tasks.huey_send_email_to_user(keyword) — @huey.task
           │
           ▼
5. Task enqueued to Redis, returns task_id
           │
           ▼
6. Response: {"ok": true, "result": {"task_id": "abc123", "status": "enqueued"}}
           │
           ▼
7. Huey container picks up task, executes:
    - Fetch emails
    - Summarize with LLM
    - Send email
    - Return result
           │
           ▼
8. Frontend polls GET /actions/status/abc123
           │
           ▼
9. Response: {"task_id": "abc123", "status": "finished", "result": {...}}
```

## Key Configuration

### .env Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `MODEL_PROVIDER` | LLM provider | openrouter |
| `OPENAI_MODEL` | Model for OpenAI | gpt-4.1-nano |
| `MODEL_TEMPERATURE` | LLM creativity | 0.5 |
| `MAX_TOKENS` | Max response length | 10500 |
| `REDIS_URL` | Valkey Redis connection | - |
| `SCHEDULE_TIME` | Default run time | 08:00 |
| `DAYS_THRESHOLD` | Default look back | 2 |
| `MAX_EMAIL_RESULTS` | Default max emails | 20 |
| `MAX_THREAD_WORKERS` | Parallel users | 5 |
| `SCHEDULE_CHECK_INTERVAL` | Minutes between checks | 5 |
| `RETRY_COUNT` | Retry attempts | 2 |
| `RETRY_DELAY` | Seconds between retries | 60 |
| `ENV_MODE` | dev/prod mode | dev |
| `EMAIL_HOST_USER` | SMTP username | - |
| `EMAIL_HOST_PASSWORD` | SMTP password | - |
| `OAUTH_CALLBACK_URL` | OAuth callback URL | - |
| `WAHA_API_URL` | WAHA server URL | http://waha:3000 |
| `WAHA_API_KEY` | WAHA API key | - |
| `WAHA_SESSION` | WAHA session name | default |
| `ADMIN_USERNAME` | Admin panel username | admin |
| `ADMIN_PASSWORD` | Admin panel password | changeme |
| `SECRET_KEY` | Session secret key | - |
| `ADMIN_PORT` | Admin panel port | 8000 |

### Scheduling Logic:
- Task runs every SCHEDULE_CHECK_INTERVAL minutes (default: 5)
- At each run, checks each user:
  - If current time >= user's schedule_time
  - If ENV_MODE=dev: always run (skip last_run check)
  - If ENV_MODE=prod: only if hasn't run today
- Email and WhatsApp tracked separately in Redis
- Each user runs once per day in PROD, multiple times in DEV

## Token Setup

### Option A: Desktop OAuth
```bash
uv run python -m modules.fetch_emails setup <keyword>
```

### Option B: Web OAuth (admin panel)
1. Open http://localhost:8000/users
2. Click red X icon next to user
3. Complete Google OAuth flow

### Option C: IPython
```bash
docker compose exec huey uv run ipython
%setup_oauth <keyword>
%check_tokens
```

## Dependencies

- **fastapi**: Admin panel web framework
- **uvicorn**: ASGI server for admin panel
- **jinja2**: Template engine for admin panel
- **pydantic-settings**: Settings management
- **huey**: Task queue & scheduler
- **google-api-python-client**: Gmail + Calendar API
- **langchain-nvidia-ai-endpoints**: NVIDIA LLM
- **langchain-openai**: OpenAI LLM
- **langchain-groq**: Groq LLM
- **langchain-google-genai**: Google Gemini
- **langchain-openrouter**: OpenRouter LLM
- **loguru**: Logging
- **redis**: Task queue backend (Valkey)
- **requests**: HTTP client for WAHA API
- **rich**: CLI formatting
- **WAHA**: WhatsApp HTTP API

## Adding New Features

### To add a new LLM provider:
1. Add entry to `MODEL_REGISTRY` in `modules/agent_utils.py`
2. Ensure langchain package in `pyproject.toml`
3. Add API key to `.env`

### To modify summary format:
- Edit prompts in `modules/prompt.py`

### To add a new huey task:
1. Add `@huey.task` decorated function in `tasks.py`
2. Add enqueue function in `admin/services.py`
3. Add route in `admin/routes/action_routes.py`

### To add a new admin panel page:
1. Add route in `admin/routes/`
2. Add template in `admin/templates/`
3. Add navigation link in `base.html`

## Environment Setup Priority

When a user is processed:
1. Per-user settings from Redis/users.json (if specified)
2. Global defaults from .env (if not in user config)

Example: If user has `"schedule_time": "09:00"` but no `max_email_results`, they get:
- schedule_time: "09:00" (from user config)
- max_email_results: 20 (from .env default)
