# Morning Mailer 🤖📧📱

AI-powered multi-user email summarization that fetches your Gmail (or multiple Gmail accounts), generates AI summaries in HTML for email and plain-text for WhatsApp, and delivers them to each user daily.

## What It Does

Every schedule check (every 5 minutes by default), Morning Mailer:
1. **Checks** each user's scheduled time in users.json
2. **Fetches** emails from Gmail (past N days per user) in parallel
3. **Categorizes** them: Critical, Important, Informational, or Ignored
4. **Summarizes** using AI into HTML (email) or plain-text (WhatsApp)
5. **Delivers** via SMTP email and/or WhatsApp (WAHA) per user preference

## New Features (v2.0+)

- **Multi-User Support**: Add multiple users with separate Gmail accounts
- **Per-User Scheduling**: Each user can have their own schedule_time
- **Per-User Settings**: Customize max_email_results, days_threshold per user
- **Parallel Processing**: Users processed concurrently
- **Smart Fallbacks**: Global .env defaults when per-user settings not specified
- **WhatsApp Integration**: Send summaries via WhatsApp using WAHA
- **Per-Channel Toggle**: Enable/disable email (`use_email`) and WhatsApp (`use_whatsapp`) per user

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Gmail OAuth credentials (one client_secret.json for all users)
- LLM API key (NVIDIA, OpenAI, Groq, or OpenRouter)
- Gmail SMTP credentials for sending emails

### 1. Get Gmail OAuth Credentials
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable Gmail API
3. Create OAuth Desktop credentials (download JSON) → save as `gauth/client_secret.json`

**Or for Web OAuth (recommended):**
1. Create OAuth Client ID → select **Web application**
2. Add authorized JavaScript origin: `http://localhost:47433`
3. Add authorized redirect URI: `http://localhost:47433/callback`
4. Download JSON → save as `gauth/client_secret_web.json`

### 2. Configure .env
Copy `.env.sample` to `.env` and fill in your values:
```bash
cp .env.sample .env
```

Or manually add to `.env`:
```bash
# LLM Provider (nvidia/openai/groq/openrouter/google)
MODEL_PROVIDER=openai
MODEL_TEMPERATURE=0.5
MAX_TOKENS=10500

# Your LLM API Keys
OPENAI_API_KEY=sk-xxxxx

# Scheduler Settings
SCHEDULE_TIME=08:00              # Default time for users without schedule_time
DAYS_THRESHOLD=2                  # Default look back days
MAX_EMAIL_RESULTS=20              # Default max emails to fetch
MAX_THREAD_WORKERS=5              # Parallel users
SCHEDULE_CHECK_INTERVAL=5          # Check every N minutes

# Email Settings (fallback for users without custom SMTP)
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

# Redis (local Valkey)
REDIS_URL=rediss://xxxxx
```

### 3. Configure users.json
Create `users.json` with your users:
```json
[
  {
    "name": "Paras",
    "email": "your-email@gmail.com",
    "keyword": "default",
    "active": true,
    "use_email": true,
    "use_whatsapp": true,
    "max_email_results": 20,
    "days_threshold": 2,
    "schedule_time": "08:00",
    "smtp_host_user": "your-email@gmail.com",
    "smtp_host_password": "your-app-password",
    "mobile": "911234567890"
  },
  {
    "name": "Work",
    "email": "work@company.com",
    "keyword": "work",
    "active": true,
    "use_email": true,
    "use_whatsapp": false,
    "max_email_results": 10,
    "schedule_time": "09:00"
  }
]
```

**Fields:**
- `name`: Display name
- `email`: Where to send email summary
- `keyword`: Unique ID (links to token_<keyword>.json)
- `active`: true/false (default: true)
- `use_email`: Enable email delivery (default: true)
- `use_whatsapp`: Enable WhatsApp delivery (default: true)
- `max_email_results`: Max emails to fetch (optional, uses .env default)
- `days_threshold`: Days to look back (optional, uses .env default)
- `schedule_time`: When to run HH:MM (optional, uses .env SCHEDULE_TIME)
- `smtp_host_user`: Custom SMTP sender (optional, falls back to .env)
- `smtp_host_password`: Custom SMTP password (optional, falls back to .env)
- `mobile`: WhatsApp number with country code, no `+` prefix (e.g., "919418168860")

### 4. First-Time OAuth Setup

#### Option A: Desktop OAuth (local machine)
```bash
# CLI - generate token for a keyword
uv run python -m modules.fetch_emails setup <keyword>

# Examples:
uv run python -m modules.fetch_emails setup default
uv run python -m modules.fetch_emails setup work
uv run python -m modules.fetch_emails setup bobyHP07

# Check token status
uv run python -m modules.fetch_emails check
```

Or in IPython:
```bash
uv run ipython
%setup_oauth work
%check_tokens
```

#### Option B: Web OAuth (remote/server via itcyou)

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

The OAuth flow will open your browser (or show URL to open). After login, token is saved to `gauth/tokens/token_<keyword>.json`.

### 5. Run
```bash
# Start the container
docker compose up -d

# Check logs
docker compose logs -f huey

# Trigger manually
docker compose exec huey python -c "from tasks import daily_email_summary; daily_email_summary()"
```

## Project Structure

```
Morning-Mailer/
├── tasks.py                    # Main scheduler & task logic
├── modules/
│   ├── fetch_emails.py        # Gmail API (keyword-based)
│   ├── agent_mod.py           # LLM wrapper
│   ├── agent_utils.py         # LLM factory
│   ├── prompt.py              # Simple HTML template
│   ├── logger.py              # Logging
│   ├── generics.py            # Utility functions
│   ├── ipython_startup.py     # IPython magic functions
│   └── ipython_config.py      # IPython configuration
├── gauth/                     # OAuth credentials
│   ├── client_secret.json     # ONE shared OAuth app
│   └── tokens/                # One token per user
│       ├── token_default.json
│       ├── token_work.json
│       └── ...
├── users.json                 # User definitions
├── users.json.sample          # User template
├── .env                       # Configuration
├── .env.sample                # Template (shareable)
├── oauth_setup.sh             # OAuth setup script
├── Dockerfile                 # Container image
└── compose.yml               # Docker orchestration
```

## Configuration

### .env Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SCHEDULE_TIME` | Default run time (HH:MM) | 08:00 |
| `DAYS_THRESHOLD` | Default days to look back | 2 |
| `MAX_EMAIL_RESULTS` | Default max emails to fetch | 20 |
| `MAX_THREAD_WORKERS` | Parallel users | 5 |
| `SCHEDULE_CHECK_INTERVAL` | Minutes between checks | 5 |
| `RETRY_COUNT` | Retry attempts | 2 |
| `RETRY_DELAY` | Seconds between retries | 60 |
| `MODEL_PROVIDER` | LLM: nvidia/openai/groq/openrouter/google | openai |
| `MODEL_TEMPERATURE` | AI creativity (0-1) | 0.5 |
| `ENV_MODE` | dev/prod: controls run frequency and log verbosity | dev |
| `EMAIL_HOST_USER` | SMTP fallback username | - |
| `EMAIL_HOST_PASSWORD` | SMTP fallback password | - |
| `OAUTH_CALLBACK_URL` | Callback URL for remote OAuth (e.g., ngrok tunnel) | - |
| `WAHA_API_URL` | WAHA server URL | http://waha:3000 |
| `WAHA_API_KEY` | WAHA API key | - |
| `WAHA_SESSION` | WAHA session name | default |

### Scheduling

- Task runs every `SCHEDULE_CHECK_INTERVAL` minutes (default: 5)
- For each user, checks if current time >= user's schedule_time
- If yes and hasn't run today → processes that user in parallel
- Users without schedule_time use global SCHEDULE_TIME from .env

### Environment Modes (`ENV_MODE`)

| Mode | Run Frequency | Log Level | Description |
|------|--------------|-----------|-------------|
| `dev` | Multiple times/day | `DEBUG` (verbose) | Skips Redis last_run check — runs every SCHEDULE_CHECK_INTERVAL when schedule time has passed. Shows all debug/info logs for troubleshooting. |
| `prod` | Once per day only | `SUCCESS` (quiet) | Enforces Redis last_run check — runs only once per day per user per channel. Only shows SUCCESS/WARNING/ERROR logs; suppresses repetitive credential loading, per-email debug lines, and intermediate info messages. |

In `prod` mode, logs are kept minimal for production monitoring. In `dev` mode, full debug output is available for local development and testing.

### Per-User Settings

Users can override:
- `max_email_results` - How many emails to fetch
- `days_threshold` - How many days back to look
- `schedule_time` - When to run (HH:MM format)

If not specified, falls back to .env defaults.

## IPython Magic Functions

Inside the container:
```bash
docker compose exec huey uv run ipython
```

| Command | Description |
|---------|-------------|
| `%daily_email_summary` | Enqueue the daily email fetch task (all users) |
| `%daily_whatsapp_summary` | Enqueue the daily WhatsApp summary task (all users) |
| `%send_email_summary <keyword\|email>` | Send email summary to a specific user |
| `%send_whatsapp_summary <keyword\|mobile>` | Send WhatsApp summary to a specific user |
| `%check_job_status <job_id>` | Check status of a Huey job |
| `%setup_oauth <keyword>` | Generate new OAuth token (desktop) |
| `%setup_web_oauth <keyword>` | Generate new OAuth token (web app) |
| `%check_tokens` | Show token status for all users |
| `%send_test_email <subject> <body>` | Send test email |
| `%send_test_whatsapp <mobile> <message>` | Send test WhatsApp message |
| `%summarize_whatsapp <keyword>` | Fetch & summarize in WhatsApp format |
| `%redis_status` | Check Redis connection |
| `%clear_last_run [keyword\|all]` | Clear last run date for testing (use in DEV mode) |
| `%cls` | Clear terminal screen |

## WhatsApp Setup (WAHA)

Morning Mailer uses [WAHA](https://waha.devlike.pro) (WhatsApp HTTP API) to send WhatsApp messages. WAHA runs as a Docker container and exposes a REST API to send/receive messages.

### Quick WAHA Setup

1. **Pull & configure WAHA** following the guide at [waha.devlike.pro/blog/waha-on-docker/](https://waha.devlike.pro/blog/waha-on-docker/)

2. **Initialize WAHA credentials** (generates API key + dashboard password):
   ```bash
   docker compose run --no-deps -v "$(pwd)":/app/env waha init-waha /app/env
   ```
   This creates credentials in a `.env` file inside WAHA's directory:
   - **Dashboard**: `http://localhost:3000/dashboard` (login with `admin / <password>`)
   - **API Key**: Copy the `WAHA_API_KEY` from the generated `.env`

3. **Start WAHA**:
   ```bash
   docker compose up -d
   ```

4. **Open the dashboard** at [http://localhost:3000/dashboard](http://localhost:3000/dashboard), enter your API key, then scan the QR code with WhatsApp on your phone to link your account.

5. **Configure Morning Mailer's `.env`** with the WAHA credentials:
   ```bash
   WAHA_API_URL=http://waha:3000          # WAHA server URL (use container name if in same compose network)
   WAHA_API_KEY=your-api-key-here         # From WAHA's .env file
   WAHA_SESSION=default                   # Session name (default: "default")
   ```

6. **Add `mobile`** field to each user in `users.json` (country code + number, no `+`):
   ```json
   { "name": "Paras", "mobile": "919418168860", "use_whatsapp": true }
   ```

7. **Done!** The WhatsApp task runs on the same schedule as email but uses separate Redis tracking keys, so both delivery channels operate independently.

For detailed WAHA setup (Nginx, HTTPS, production hardening), see the [WAHA on Docker guide](https://waha.devlike.pro/blog/waha-on-docker/).

## Manual Testing

```bash
# Run task directly
docker compose exec huey python -c "
from tasks import fetch_emails_with_retry, summarize_emails
result = fetch_emails_with_retry('default', 20, 2)
if result['emails']:
    summary = summarize_emails(result['emails'])
    print(summary)
"

# Send test email
docker compose exec huey python -c "
from tasks import send_email
send_email('your@email.com', 'Test', 'Hello World')
"
```

## Logs

View real-time logs:
```bash
docker compose logs -f huey
```

## Troubleshooting

### No module named 'xxx'
```bash
docker compose build --no-cache
docker compose up -d
```

### Gmail credentials not found
- Ensure `gauth/client_secret.json` exists
- Ensure `gauth/tokens/token_<keyword>.json` exists for each user

### Redis connection refused
- Check `REDIS_URL` in `.env`
- Ensure container can reach the Valkey Redis instance

### Email sending fails
- Check `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` in `.env`
- Or set per-user `smtp_host_user` and `smtp_host_password` in users.json
- Use Gmail App Password (not your regular password)

### OAuth token not found for user
```bash
# Generate new token
uv run python -m modules.fetch_emails setup <keyword>
# Or use IPython
%setup_oauth keyword
```

## Tech Stack

- **Task Queue**: Huey (Redis-backed)
- **Gmail API**: google-api-python-client
- **LLM**: LangChain (NVIDIA, OpenAI, Groq, OpenRouter, Google)
- **Logging**: loguru
- **Email**: smtplib (SMTP)
- **Container**: Docker + Docker Compose

## License

MIT