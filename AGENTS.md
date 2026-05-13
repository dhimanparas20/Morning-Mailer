# Morning Mailer - Codebase Documentation for AI Agents

## Project Overview

Morning Mailer is an AI-powered **multi-user** email summarization system that automatically fetches emails from multiple Gmail accounts at scheduled times, generates summaries using Large Language Models, and delivers them via email (HTML) and/or WhatsApp (plain text) to each user.

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│  Gmail API     │────▶│ Huey Worker  │────▶│  LLM (NVIDIA/
│  (Email Fetch) │     │ (Scheduler)  │     │  OpenAI/    │
└─────────────────┘     └──────────────┘     │  Groq)       │
          │                      │              └─────────────┘
          │              ┌──────┴──────┐
          │              │   Redis      │
           │              │ (Valkey)   │
          │              └─────────────┘
          ▼
    ┌──────────────────────────────────────┐
    │         Summary Output               │
    │  - HTML summaries via SMTP email     │
    │  - Plain text via WhatsApp (WAHA)    │
    │  - Per-user channel toggles          │
    │  - Color-coded sections (email)      │
    └──────────────────────────────────────┘
```

## Key Features

1. **Multi-User Support**: Multiple users with separate Gmail accounts
2. **Per-User Scheduling**: Each user can have their own schedule_time
3. **Parallel Processing**: Users processed concurrently with ThreadPoolExecutor
4. **Smart Fallbacks**: Global defaults when per-user settings not specified
5. **Token Management**: Single OAuth credentials + multiple tokens
6. **DEV/PROD Mode**: DEV = run multiple times/day (verbose DEBUG logs), PROD = run once/day (quiet SUCCESS-level logs)
7. **WhatsApp Integration**: Send summaries via WhatsApp using WAHA API
8. **Per-Channel Toggles**: `use_email` and `use_whatsapp` per-user booleans

## Core Components

### 1. tasks.py - Task Scheduler & Main Logic
- **Purpose**: Orchestrates email fetching, summarization, and sending for all users
- **Key Functions**:
  - `load_users()`: Loads active users from Redis first, falls back to users.json, then .env
  - `get_user_settings(user)`: Gets per-user max_email_results & days_threshold
  - `should_run_today(user, global_schedule_time, redis_prefix="")`: Checks if user's schedule time has passed today (redis_prefix isolates email vs WhatsApp tracking)
  - `get_user_last_run_date(keyword)`: Gets last processed date from Redis
  - `set_user_last_run_date(keyword, date_str)`: Updates last processed date in Redis
  - `fetch_emails_with_retry(keyword, max_results, days_threshold)`: Fetches with per-user settings
  - `process_user(user, global_schedule_time)`: Full pipeline for one user
  - `send_email(to, subject, body, is_html, smtp_user, smtp_password)`: Sends via SMTP
  - `send_whatsapp(mobile, text)`: Sends WhatsApp via WAHA API
  - `daily_email_summary()`: Huey periodic task - runs every SCHEDULE_CHECK_INTERVAL minutes (email delivery)
  - `daily_whatsapp_summary()`: Huey periodic task - WhatsApp delivery (separate Redis tracking, respects use_whatsapp)

- **Scheduling Logic**:
  - Task runs every N minutes (SCHEDULE_CHECK_INTERVAL, default: 5)
  - For each user, checks if current time >= user's schedule_time
  - Email task tracks processed in Redis (key: `morning_mailer:last_run:<keyword>`)
  - WhatsApp task tracks separately (key: `morning_mailer:whatsapp_last_run:<keyword>`)
  - `use_email` / `use_whatsapp` per-user booleans control which channel runs

### 2. modules/fetch_emails.py - Gmail Integration
- **Purpose**: Handles all Gmail API interactions
- **Key Functions**:
  - `get_gmail_service(keyword)`: Initializes Gmail API client with OAuth (per keyword)
  - `fetch_emails(keyword, max_results, query, date_from, date_to, ...)`: Main API
  - `get_token_path(keyword)`: Returns path to token_<keyword>.json
  - `get_credentials_path()`: Returns path to client_secret.json (shared)
  - `load_users()`: Loads users from users.json
  - `parse_date()`, `clean_text()`, `extract_plain_text()`: Utilities

- **OAuth Structure** (SINGLE SECRET, MULTIPLE TOKENS):
  ```
  gauth/
  ├── client_secret.json         ← Desktop OAuth app (legacy)
  ├── client_secret_web.json     ← Web OAuth app (recommended)
  └── tokens/
      ├── token_dhimanparas20.json  ← User 1's token
      ├── token_bobyHP07.json        ← User 2's token
      └── token_lgtvmistanbul.json   ← User 3's token
  ```

- **Parallel Fetching**: Uses ThreadPoolExecutor for thread-safe email fetching

### 2.1 modules/web_auth.py - Web OAuth Setup

### 2.2 modules/redis_users.py - Redis User Storage
- **Purpose**: Store and manage users as Redis hashes (alternative to users.json)
- **Key Pattern**: `USERS_CONFIG:<keyword>` — each user is a Redis hash, keywords tracked in `USERS_CONFIG:keywords` SET
- **Key Classes**:
  - `RedisUserManager(r)`: Full CRUD with pipelined bulk reads/writes
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
- **CLI Tool**: `cli_users.py` (argparse + Rich tables) — list, show, add, update, remove, activate, deactivate, import, export, clear, fields
- **IPython Magics**: `%redis_users_list`, `%redis_users_show`, `%redis_users_add`, `%redis_users_update`, `%redis_users_remove`, `%redis_users_activate`, `%redis_users_deactivate`, `%redis_users_import`, `%redis_users_export`, `%redis_users_clear`, `%redis_users_fields`
- **Fallback**: `tasks.load_users()` tries Redis first; if empty/error, falls back to `users.json` → `.env` defaults

### 3. modules/agent_mod.py - LLM Integration
- **Purpose**: Wrapper for LLM summarization
- **Key Functions**:
  - `init()`: Initializes LLM from config (MODEL_PROVIDER)
  - `summarize_emails(emails, prompt)`: Generates HTML summary

- **Supported Providers**: nvidia, openai, groq, openrouter, google

### 4. modules/prompt.py - Prompt Templates
- **Purpose**: Defines LLM output format for both email and WhatsApp
- **Variables**:
  - `EMAIL_SYSTEM_PROMPT`: HTML summary format with inline CSS
  - `WHATSAPP_SYSTEM_PROMPT`: Plain-text WhatsApp format with *bold*, _italic_, emoji markers
  - `SYSTEM_PROMPT`: Backward-compat alias for EMAIL_SYSTEM_PROMPT
- **Features**:
  - Clean, minimal layout with inline CSS (email)
  - Color-coded sections (red=critical, green=important, blue=info)
  - WhatsApp-compatible formatting (bold, italic, emojis, bullets)
  - Minimal token usage for cost efficiency

### 5. modules/ipython_startup.py - Magic Functions
- **Available Magic Functions**:
  - `%daily_email_summary`: Trigger the task (all users, respects schedule)
  - `%daily_whatsapp_summary`: Trigger WhatsApp summary task (all users, respects schedule)
  - `%force_email_summary`: Force email summary for ALL users immediately (ignores schedule)
  - `%force_whatsapp_summary`: Force WhatsApp summary for ALL users immediately (ignores schedule)
  - `%send_email_summary <keyword|email>`: Send email summary to a specific user only
  - `%send_whatsapp_summary <keyword|mobile>`: Send WhatsApp summary to a specific user only
  - `%check_job_status <job_id>`: Check Huey job
  - `%setup_oauth <keyword>`: Generate new token (desktop)
  - `%setup_web_oauth <keyword>`: Generate new token (web app)
  - `%check_tokens`: Show token status for all users (Redis + users.json)
  - `%send_test_email <subject> <body>`: Test SMTP
  - `%send_test_whatsapp <mobile> <message>`: Test WhatsApp message
  - `%summarize_whatsapp <keyword>`: Fetch & summarize in WhatsApp format
  - `%run_summarize <keyword>`: Fetch & summarize in HTML email format
  - `%run_fetch <keyword>`: Fetch emails directly (no Huey)
  - `%redis_status`: Check Redis connection
  - `%redis_users_list`: List all users in Redis
  - `%redis_users_show <keyword>`: Show one user's details
  - `%redis_users_add --name X --email Y --keyword Z ...`: Add user to Redis
  - `%redis_users_update <keyword> --field value ...`: Update user in Redis
  - `%redis_users_remove <keyword>`: Remove user from Redis
  - `%redis_users_activate <keyword>`: Activate a user in Redis
  - `%redis_users_deactivate <keyword>`: Deactivate a user in Redis
  - `%redis_users_import [file]`: Import users.json into Redis
  - `%redis_users_export [file]`: Export Redis users to JSON
  - `%redis_users_clear yes`: Delete ALL users from Redis
  - `%redis_users_fields`: Show available user fields and types
  - `%clear_last_run [keyword|all]`: Clear last run date (use in DEV mode)
  - `%cls`: Clear terminal

## Data Flow

```
1. Huey scheduler triggers every SCHEDULE_CHECK_INTERVAL minutes
           │
           ▼
2. daily_email_summary() called
           │
           ▼
3. For each active user in Redis (USERS_CONFIG:<keyword>) or users.json:
    ├── Check if current time >= user's schedule_time
    ├── Check ENV_MODE:
    │    ├── dev: skip last_run check → always eligible
    │    └── prod: check Redis (key: morning_mailer:last_run:<keyword>)
    └── If eligible → add to eligible_users
           │
           ▼
4. Eligible users processed in parallel (ThreadPoolExecutor)
           │
           ▼
5. For each eligible user:
    ├── fetch_emails_with_retry(keyword, user_max_results, user_days_threshold)
    │    - Uses user's max_email_results (or global default)
    │    - Uses user's days_threshold (or global default)
    ├── summarize_emails(emails)
    ├── send_email(to=user_email, smtp_host=user_smtp)
    └── set_user_last_run_date(keyword, today)
           │
           ▼
6. Return: {date, time, eligible_users, processed, total_emails_fetched, results}
```

## File Structure

```
Morning-Mailer/
├── tasks.py                    # Main scheduler (per-user scheduling)
├── modules/
│   ├── fetch_emails.py         # Gmail API (keyword-based tokens)
│   ├── agent_mod.py            # LLM wrapper
│   ├── agent_utils.py          # LLM factory
│   ├── prompt.py               # Simple HTML template
│   ├── logger.py              # Logging
│   ├── generics.py            # Utilities
│   ├── redis_users.py         # Redis user storage & CRUD
│   └── ipython_startup.py     # IPython magic functions
├── cli_users.py                # CLI for Redis user management
├── gauth/
│   ├── client_secret.json      # Single OAuth credentials (shared)
│   └── tokens/                 # One token per user
│       ├── token_<keyword>.json
│       └── ...
├── users.json                  # Multi-user configuration
├── users.json.sample           # User template
├── .env                        # Global settings
├── .env.sample                 # Environment template
├── oauth_setup.sh              # OAuth setup script
├── compose.yml                 # Docker orchestration
└── pyproject.toml              # Dependencies
```

## Multi-User Support

### users.json Schema

```json
[
  {
    "name": "Paras",
    "email": "dhimanparas20@gmail.com",
    "keyword": "dhimanparas20",
    "active": true,
    "use_email": true,
    "use_whatsapp": true,
    "max_email_results": 20,      // optional, falls back to .env
    "days_threshold": 2,            // optional, falls back to .env
    "schedule_time": "08:00",       // optional, falls back to .env SCHEDULE_TIME
    "smtp_host_user": "user@gmail.com",   // optional, falls back to .env
    "smtp_host_password": "xxxx",          // optional, falls back to .env
    "mobile": "919418168860"               // WhatsApp number (country code, no +)
  }
]
```

### Per-User Fields:
| Field | Required | Default | Description |
|-------|----------|---------|--------------|
| `name` | Yes | - | Display name |
| `email` | Yes | - | Where to send summary |
| `keyword` | Yes | - | Links to token_<keyword>.json |
| `active` | No | true | If false, user is skipped |
| `use_email` | No | true | Enable/disable email delivery |
| `use_whatsapp` | No | true | Enable/disable WhatsApp delivery |
| `max_email_results` | No | .env MAX_EMAIL_RESULTS | Max emails to fetch |
| `days_threshold` | No | .env DAYS_THRESHOLD | Days to look back |
| `schedule_time` | No | .env SCHEDULE_TIME | When to run (HH:MM) |
| `smtp_host_user` | No | .env EMAIL_HOST_USER | Custom SMTP sender |
| `smtp_host_password` | No | .env EMAIL_HOST_PASSWORD | Custom SMTP password |
| `mobile` | No | - | WhatsApp number with country code |

### Scheduling Logic:
- Task runs every SCHEDULE_CHECK_INTERVAL minutes (default: 5)
- At each run, checks each user:
  - If current time >= user's schedule_time (or global SCHEDULE_TIME)
  - If ENV_MODE=dev: always run (skip last_run check) + verbose DEBUG logs
  - If ENV_MODE=prod: only if hasn't run today (tracked in Redis) + quiet SUCCESS-level logs
  - THEN process that user in parallel
- Each user runs once per day in PROD mode, multiple times in DEV mode
- Users without schedule_time use global SCHEDULE_TIME from .env

## Key Configuration

### .env Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `MODEL_PROVIDER` | LLM provider (nvidia/openai/groq/openrouter/google) | openrouter |
| `OPENAI_MODEL` | Model for OpenAI | gpt-4.1-nano |
| `MODEL_TEMPERATURE` | LLM creativity | 0.5 |
| `MAX_TOKENS` | Max response length | 10500 |
| `REDIS_URL` | Valkey Redis connection string | (your URL) |
| `SCHEDULE_TIME` | Default run time (when user has no schedule_time) | 08:00 |
| `DAYS_THRESHOLD` | Default look back period | 2 |
| `MAX_EMAIL_RESULTS` | Default max emails to fetch | 20 |
| `MAX_THREAD_WORKERS` | Parallel users/processes | 5 |
| `SCHEDULE_CHECK_INTERVAL` | Minutes between scheduler checks | 5 |
| `RETRY_COUNT` | Retry attempts on failure | 2 |
| `RETRY_DELAY` | Seconds between retries | 60 |
| `ENV_MODE` | dev = run multiple times + verbose logs, prod = run once/day + quiet logs | dev |
| `EMAIL_HOST_USER` | Fallback SMTP username | (your email) |
| `EMAIL_HOST_PASSWORD` | Fallback SMTP password | (app password) |
| `OAUTH_CALLBACK_URL` | Callback URL for remote OAuth (e.g., ngrok tunnel) | - |
| `WAHA_API_URL` | WAHA server URL | http://waha:3000 |
| `WAHA_API_KEY` | WAHA API key | - |
| `WAHA_SESSION` | WAHA session name | default |

## Token Setup

### Option A: Desktop OAuth (local machine)
```bash
# Using CLI
uv run python -m modules.fetch_emails setup <keyword>

# Examples:
uv run python -m modules.fetch_emails setup work
uv run python -m modules.fetch_emails setup bobyHP07
uv run python -m modules.fetch_emails setup myname

# Using IPython
%setup_oauth work
```

### Option B: Web OAuth (remote/server via itcyou)

For server/remote setups without browser access, use Web OAuth with itcyou tunnel:

1. **Start itcyou tunnel** (choose your subdomain):
```bash
docker run -d --rm --network host --name itcyou \
  -e ITCYOU_PORT=47433 \
  -e ITCYOU_SUBDOMAIN=morning-mailer \
  dhimanparas20/itcyou:latest
```

2. **Configure Google Cloud Console** with your domain:
   - Authorized JavaScript origin: `https://morning-mailer.it.cyou`
   - Authorized redirect URI: `https://morning-mailer.it.cyou/callback`

3. **Download OAuth JSON** → save as `gauth/client_secret_web.json`

4. **Set callback URL in .env**:
```bash
OAUTH_CALLBACK_URL=https://morning-mailer.it.cyou/callback
```

5. **Generate token**:
```bash
# CLI
uv run python -m modules.web_auth <keyword>

# Or in IPython
%setup_web_oauth keyword
```

### Checking Token Status:
```bash
# CLI
uv run python -m modules.fetch_emails check

# IPython
%check_tokens
```

This will show which users have tokens and which need OAuth setup.

## IPython Magic Functions

In IPython (`docker compose exec huey uv run ipython`):

| Magic | Usage | Description |
|-------|-------|-------------|
| `%daily_email_summary` | `%daily_email_summary` | Trigger the scheduled task (all users) |
| `%daily_whatsapp_summary` | `%daily_whatsapp_summary` | Trigger WhatsApp summary task (all users) |
| `%send_email_summary` | `%send_email_summary <keyword\|email>` | Send email summary to a specific user |
| `%send_whatsapp_summary` | `%send_whatsapp_summary <keyword\|mobile>` | Send WhatsApp summary to a specific user |
| `%check_job_status` | `%check_job_status <job_id>` | Check Huey job status |
| `%setup_oauth` | `%setup_oauth <keyword>` | Generate new token (desktop) |
| `%setup_web_oauth` | `%setup_web_oauth <keyword>` | Generate new token (web app) |
| `%check_tokens` | `%check_tokens` | Show all users' token status |
| `%send_test_email` | `%send_test_email <subject> <body>` | Send test email |
| `%send_test_whatsapp` | `%send_test_whatsapp <mobile> <message>` | Send test WhatsApp message |
| `%summarize_whatsapp` | `%summarize_whatsapp <keyword>` | Fetch & summarize in WhatsApp format |
| `%redis_status` | `%redis_status` | Check Redis connection |
| `%clear_last_run` | `%redis_users_clear yes` | Delete ALL users from Redis |
| `%redis_users_fields` | Show all available user fields |
| `%clear_last_run [keyword\|all]` | Clear last run date (use in DEV mode) |
| `%run_fetch` | `%run_fetch` | Direct fetch (no Huey) |
| `%cls` | `%cls` | Clear terminal |

## Common Tasks

### Manual Trigger:
```bash
docker compose exec huey python -c "from tasks import daily_email_summary; daily_email_summary()"
```

### Check Logs:
```bash
docker compose logs -f huey
```

### Rebuild Container:
```bash
docker compose build --no-cache && docker compose up -d
```

### Test Fetch for Specific User:
```python
from tasks import fetch_emails_with_retry
result = fetch_emails_with_retry("dhimanparas20", 20, 2)
print(result['count'], "emails")
```

### Test Send Email:
```python
from tasks import send_email
send_email("test@example.com", "Test Subject", "Hello!")
```

## Adding New Features

### To add a new LLM provider:
1. Add entry to `MODEL_REGISTRY` in `modules/agent_utils.py`
2. Ensure langchain package in `pyproject.toml`
3. Add API key to `.env`

### To modify summary format:
- Edit `SYSTEM_PROMPT` in `modules/prompt.py`

### To add per-user settings:
- Add field to users.json
- Update `get_user_settings()` in tasks.py to read it

## Dependencies

- **huey**: Task queue & scheduler
- **google-api-python-client**: Gmail API
- **langchain-nvidia-ai-endpoints**: NVIDIA LLM
- **langchain-openai**: OpenAI LLM
- **langchain-groq**: Groq LLM
- **langchain-google-genai**: Google Gemini
- **loguru**: Logging
- **redis**: Task queue backend (Valkey)
- **requests**: HTTP client for WAHA WhatsApp API calls
- **WAHA** ([waha.devlike.pro](https://waha.devlike.pro)): WhatsApp HTTP API (separate Docker container) — provides REST API at `http://waha:3000` for sending messages. Dashboard at `:3000/dashboard` for QR-based WhatsApp Web pairing. Setup guide: https://waha.devlike.pro/blog/waha-on-docker/

## Environment Setup Priority

When a user is processed:
1. Per-user settings from users.json (if specified)
2. Global defaults from .env (if not in users.json)

Example: If user has `"schedule_time": "09:00"` but no `max_email_results`, they get:
- schedule_time: "09:00" (from users.json)
- max_email_results: 20 (from .env default)