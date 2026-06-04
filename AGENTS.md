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

### Why This Separation Matters

- The `app` container imports `tasks.py` but NEVER calls heavy functions directly
- The LLM agent (`AGENT`) is `None` at module level — lazily initialized only by `get_agent()`
- `print_startup_summary()` only runs once inside `daily_summary()` (guarded by `_startup_summary_printed` flag)
- `admin/services.py` imports `tasks` once at startup — NO `importlib.reload()`
- This means starting the admin panel does NOT load the LLM, does NOT print startup tables, does NOT waste memory

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
- Also defines `CLIENT_SECRET_WEB_PATH` and `CLIENT_SECRET_PATH` for OAuth

#### 2.3 admin/auth.py - Authentication
- Session-based auth (not JWT)
- CSRF protection via double-submit cookie
- `AuthMiddleware` intercepts requests, checks session
- `EXEMPT_PATHS = {"/login", "/static", "/favicon.ico", "/oauth/callback"}` — callback MUST be exempt or OAuth flow breaks
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
  - `generate_oauth_url(keyword)` — Creates Google OAuth URL (uses `client_secret_web.json` first, falls back to `client_secret.json`)
  - `exchange_oauth_code(code, keyword)` — Exchanges auth code for token
- **Note**: Tasks module is imported once at startup (no `importlib.reload`) to avoid re-initializing module-level code in the app container.
- **Logging**: Uses `modules.logger.get_logger("Admin Services")` for all operations

#### 2.6 admin/routes/ - API Routes

| Router | Prefix | Purpose |
|--------|--------|---------|
| `auth_routes` | `/login`, `/logout` | Login/logout with CSRF |
| `user_routes` | `/users` | User CRUD, search/sort, import/export |
| `action_routes` | `/actions` | Trigger email/whatsapp/calendar actions, test send, model switch |
| `oauth_routes` | `/oauth` | OAuth start + callback |
| `system_routes` | `/system` | Redis status, scheduler status, tokens status |

**Important Route Ordering in oauth_routes.py**: `/callback` MUST be defined BEFORE `/{keyword}` otherwise FastAPI matches `callback` as a keyword. The `/callback` path is the fixed OAuth callback URL used by Google redirect.

**User Form Routes**:
- `GET /users/{keyword}/edit` — renders edit form, passes `success_msg` from `?updated=1` query param
- `POST /users/{keyword}/edit` — updates user, redirects to `GET /users/{keyword}/edit?updated=1` (303 redirect, NOT JSON)
- `POST /users/add` — creates user, returns JSON

**Checkbox Handling in Forms**: HTML checkboxes send nothing when unchecked. The `user_form.html` template uses JavaScript to add hidden inputs with `value="false"` for unchecked checkboxes on form submit. Routes receive `"true"` or `"false"` strings and compare with `== "true"`.

#### 2.7 admin/templates/ - Jinja2 Templates

| Template | Purpose |
|----------|---------|
| `base.html` | Base layout (navbar, Bootstrap 5, glassmorphism theme). Has `{% block navbar %}` for hiding on login/oauth pages, `{% block body_class %}` for custom body classes, `{% block scripts %}` for page-specific JS |
| `login.html` | Login page (no navbar, centered card) |
| `dashboard.html` | Stats cards, quick actions, scheduler config, users overview |
| `users.html` | User list with search/sort/filter, action buttons, OAuth setup button + copy button for users without tokens |
| `user_form.html` | Add/edit user form with section headers, .env SMTP fallback placeholders, checkbox JS fix, success toast via `?updated=1` |
| `oauth_redirect.html` | Redirects to Google OAuth. Uses `{{ auth_url | safe }}` in script tag (NOT `{{ auth_url }}` — Jinja2 escapes `&` to `&amp;` which breaks OAuth URLs) |
| `oauth_result.html` | Shows OAuth success/failure with link back to users |

#### 2.8 admin/static/ - Static Files
- `css/style.css` — Purple gradient glassmorphism theme
- `js/app.js` — Toast notifications (`showToast()`), action handlers (`action-btn-sm`), task status polling (`pollTaskStatus()`, `enqueue_task()`)

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

- **OAuth Scopes**: `gmail.readonly` + `calendar.readonly`
- **Token Sharing**: Gmail and Calendar share the same token file per keyword

### 4. modules/web_auth.py - Web OAuth Setup
- Handles OAuth flow for web/remote setups
- `get_auth_url(client_config, state)`: Generates Google OAuth URL with all required params
- `exchange_code_for_token(code, client_config)`: Exchanges auth code for access/refresh tokens
- `get_callback_url()`: Returns `OAUTH_CALLBACK_URL` from env (default: `http://localhost:8000/oauth/callback`)
- `get_credential_type(client_config)`: Detects `"web"` vs `"installed"` (desktop) client type
- `get_client_id(client_config)`, `get_client_secret(client_config)`: Extract from config
- `load_client_config()`: Loads `client_secret_web.json` first, falls back to `client_secret.json`

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
- **ALL_FIELDS**: `name`, `email`, `keyword`, `active`, `use_email`, `use_whatsapp`, `fetch_calendar`, `max_email_results`, `days_threshold`, `schedule_time`, `smtp_host_user`, `smtp_host_password`, `mobile`
- **BOOL_FIELDS**: `active`, `use_email`, `use_whatsapp`, `fetch_calendar`
- **INT_FIELDS**: `max_email_results`, `days_threshold`

### 7. modules/agent_mod.py - LLM Integration
- **Purpose**: Wrapper for LLM summarization
- **Key Functions**:
  - `init()`: Initializes LLM from config (MODEL_PROVIDER)
  - `summarize_emails(emails, prompt, user_name, calendar_events)`: Generates summary
  - `hot_switch_model(provider, model_name, temperature)`: Hot-swap LLM at runtime
- **Supported Providers**: nvidia, openai, groq, openrouter, google

### 8. modules/agent_utils.py - LLM Factory
- `create_llm(model_name, api_key, model_provider, model_temperature, max_tokens)`: Factory function
- `MODEL_REGISTRY`: Dict mapping provider names to config (module, class, api_key_env, model_env)

### 9. modules/prompt.py - Prompt Templates
- **Variables**:
  - `EMAIL_SYSTEM_PROMPT`: HTML summary format with inline CSS
  - `WHATSAPP_SYSTEM_PROMPT`: Plain-text WhatsApp format with *bold*, _italic_, emoji markers
  - `CALENDAR_EMAIL_PROMPT`: Calendar events → HTML email format
  - `CALENDAR_WHATSAPP_PROMPT`: Calendar events → WhatsApp format
  - `SYSTEM_PROMPT`: Backward-compat alias for EMAIL_SYSTEM_PROMPT

### 10. modules/logger.py - Logging
- Uses loguru with custom format
- `get_logger(module_name, show_time=True)`: Returns a bound logger
- `add_file_logger(log_path, rotation, retention)`: Adds file handler
- Format: `LEVEL | MODULE_NAME | message` (with optional timestamp)
- Respects `ENV_MODE`: DEBUG in dev, INFO in prod

### 11. modules/ipython_startup.py - Magic Functions
- Available in IPython inside the huey container
- Provides `%daily_email_summary`, `%send_email_summary <keyword>`, etc.

## File Structure

```
Morning-Mailer/
├── tasks.py                    # Huey tasks & scheduling
├── admin/                      # FastAPI admin panel
│   ├── main.py                 # App entry point
│   ├── config.py               # Settings from .env
│   ├── auth.py                 # Session auth + CSRF + AuthMiddleware
│   ├── models.py               # Pydantic models
│   ├── services.py             # Business logic (enqueues huey tasks, logging)
│   ├── routes/
│   │   ├── auth_routes.py      # Login/logout (logging)
│   │   ├── user_routes.py      # User CRUD (logging, edit redirects with ?updated=1)
│   │   ├── action_routes.py    # Trigger actions (logging)
│   │   ├── oauth_routes.py     # OAuth flow (/callback BEFORE /{keyword}!)
│   │   └── system_routes.py    # Redis/scheduler status (logging)
│   ├── templates/              # Jinja2 HTML templates
│   │   ├── base.html           # Base layout (navbar block, scripts block)
│   │   ├── login.html          # Login page (no navbar)
│   │   ├── dashboard.html      # Dashboard with stats/actions
│   │   ├── users.html          # User list with search/sort, OAuth setup + copy buttons
│   │   ├── user_form.html      # Add/edit form (checkbox JS fix, SMTP placeholders, success toast)
│   │   ├── oauth_redirect.html # OAuth redirect (uses | safe filter for URLs in scripts)
│   │   └── oauth_result.html   # OAuth result page
│   └── static/
│       ├── css/style.css       # Purple gradient glassmorphism theme
│       └── js/app.js           # Toast notifications + task polling
├── modules/
│   ├── fetch_emails.py         # Gmail API
│   ├── fetch_calendar.py       # Google Calendar API
│   ├── agent_mod.py            # LLM wrapper
│   ├── agent_utils.py          # LLM factory (MODEL_REGISTRY)
│   ├── prompt.py               # Prompt templates
│   ├── logger.py               # Logging (get_logger)
│   ├── generics.py             # Utilities
│   ├── redis_users.py          # Redis user storage
│   ├── web_auth.py             # Web OAuth (get_auth_url, exchange_code_for_token)
│   └── ipython_startup.py      # IPython magics
├── cli_users.py                # CLI for Redis user management
├── gauth/
│   ├── client_secret.json      # Desktop OAuth (shared)
│   ├── client_secret_web.json  # Web OAuth (recommended)
│   └── tokens/                 # One token per user
│       ├── token_<keyword>.json
│       └── ...
├── users.json                  # User definitions (fallback)
├── .env                        # Configuration
├── .env.sample                 # Environment template
├── Dockerfile                  # Container image
├── compose.yml                 # Docker orchestration (4 services)
├── pyproject.toml              # Dependencies
├── README.md                   # Human-readable docs
└── AGENTS.md                   # This file (LLM-facing docs)
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

### Scheduled Processing
```
1. Huey scheduler triggers every SCHEDULE_CHECK_INTERVAL minutes
           │
           ▼
2. daily_summary() called
    └── On first run: prints startup summary (guarded by _startup_summary_printed)
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
    ├── Summarize with LLM (get_agent().summarize_emails())
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

### OAuth Flow (Admin Panel)
```
1. User clicks "Setup" button on users page
           │
           ▼
2. GET /oauth/{keyword}
    └── services.generate_oauth_url(keyword)
        ├── Loads client_secret_web.json (or client_secret.json)
        ├── Uses OAUTH_CALLBACK_URL from .env
        └── Returns full Google OAuth URL
           │
           ▼
3. oauth_redirect.html renders with auth_url
    └── Uses {{ auth_url | safe }} in <script> (NOT {{ auth_url }} — & gets escaped to &amp;)
    └── Auto-redirects after 1.5s + shows manual "Open" button
           │
           ▼
4. User authorizes on Google
           │
           ▼
5. Google redirects to /oauth/callback?state={keyword}&code={code}
    └── AuthMiddleware EXEMPT for /oauth/callback (no session needed)
    └── Route /callback defined BEFORE /{keyword} to avoid matching as keyword="callback"
           │
           ▼
6. oauth_callback() extracts keyword from state param
    └── services.exchange_oauth_code(code, keyword)
        ├── Exchanges code for tokens
        └── Saves to gauth/tokens/token_{keyword}.json
           │
           ▼
7. Renders oauth_result.html with success/failure
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
| `OAUTH_CALLBACK_URL` | OAuth callback URL | http://localhost:8000/oauth/callback |
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

### Environment Modes (`ENV_MODE`)
| Mode | Run Frequency | Log Level | Description |
|------|--------------|-----------|-------------|
| `dev` | Multiple times/day | DEBUG | Skips Redis last_run check, verbose logs |
| `prod` | Once per day only | SUCCESS | Enforces Redis last_run check, minimal logs |

## Token Setup

### Option A: Desktop OAuth
```bash
uv run python -m modules.fetch_emails setup <keyword>
```

### Option B: Web OAuth (admin panel)
1. Open http://localhost:8000/users
2. Click "Setup" button next to user without token
3. Complete Google OAuth flow
4. Token saved to `gauth/tokens/token_{keyword}.json`

**Google Cloud Console Requirements for Web OAuth:**
- Authorized redirect URI: `http://localhost:8000/oauth/callback`
- Authorized JS origin: `http://localhost:8000`

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

## Logging

All admin modules use `modules.logger.get_logger("Module Name")`:

| Module | Logger Name |
|--------|-------------|
| `admin/services.py` | `Admin Services` |
| `admin/routes/user_routes.py` | `Admin Routes` |
| `admin/routes/action_routes.py` | `Admin Actions` |
| `admin/routes/auth_routes.py` | `Admin Auth` |
| `admin/routes/oauth_routes.py` | `Admin OAuth` |
| `admin/routes/system_routes.py` | `Admin System` |
| `tasks.py` | `tasks` (uses raw loguru) |

Log levels used: `log.info()` for actions, `log.success()` for completed operations, `log.warning()` for non-critical issues, `log.error()` for failures.

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
4. Add log calls using `modules.logger.get_logger()`

### To add a new admin panel page:
1. Add route in `admin/routes/`
2. Add template in `admin/templates/`
3. Add navigation link in `base.html`

### To add a new user form field:
1. Add to `ALL_FIELDS` in `modules/redis_users.py`
2. Add to `BOOL_FIELDS` or `INT_FIELDS` if applicable
3. Add form input in `admin/templates/user_form.html`
4. Add field handling in `admin/routes/user_routes.py` (both add and edit routes)
5. Update `user_fields()` in `admin/services.py` descriptions

## Environment Setup Priority

When a user is processed:
1. Per-user settings from Redis/users.json (if specified)
2. Global defaults from .env (if not in user config)

Example: If user has `"schedule_time": "09:00"` but no `max_email_results`, they get:
- schedule_time: "09:00" (from user config)
- max_email_results: 20 (from .env default)

## Known Pitfalls & Solutions

1. **Jinja2 auto-escaping in `<script>` tags**: `{{ url }}` escapes `&` to `&amp;`. Use `{{ url | safe }}` for URLs in script tags.

2. **HTML checkboxes send nothing when unchecked**: Add hidden inputs or use JS to inject them on form submit. See `user_form.html` `.toggle-field` pattern.

3. **FastAPI route matching order**: Fixed paths (`/callback`) must be defined BEFORE dynamic paths (`/{keyword}`) or they'll be captured as path params.

4. **Auth middleware must exempt OAuth callback**: The `/oauth/callback` path needs no session. Add to `EXEMPT_PATHS` in `auth.py`.

5. **Edit form should redirect, not return JSON**: Use `RedirectResponse(url=..., status_code=303)` after POST, then check `?updated=1` query param in GET to show toast.

6. **LLM must not load in app container**: `AGENT = None` at module level, `get_agent()` is lazy. Never call `AGENT.init()` at import time.

7. **Startup summary must not repeat**: Guard with `_startup_summary_printed` flag, call only inside `daily_summary()`.

8. **OAuth callback URL must match port**: `OAUTH_CALLBACK_URL` in `.env` must match the actual host port the admin panel is accessible on.

9. **Docker bind mount stale cache**: If a file was created after container start, `Path.exists()` may return False even though `ls` shows it. Restart or rebuild the container.

10. **SMTP form placeholders**: Pass `.env` values to template as `env_smtp_user`/`env_smtp_password` for placeholder display. User's custom values go in `value=""`, not placeholder.
