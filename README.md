# Morning Mailer 🤖📧

AI-powered email summarization that fetches your Gmail, generates an AI summary in HTML, and emails it to you daily.

## What It Does

Every morning (or on your schedule), Morning Mailer:
1. **Fetches** your recent emails from Gmail (past N days)
2. **Categorizes** them: Critical, Important, Informational, or Ignored
3. **Summarizes** using AI into a beautiful HTML briefing
4. **Emails** the summary to your inbox

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Gmail OAuth credentials (see below)
- LLM API key (NVIDIA, OpenAI, Groq, or OpenRouter)
- Gmail SMTP credentials for sending emails

### 1. Get Gmail OAuth Credentials
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable Gmail API
3. Create OAuth Desktop credentials (download JSON)
4. Place as `gauth/client_secret.json`

### 2. Configure .env
```bash
# LLM Provider (nvidia/openai/groq/openrouter/google)
MODEL_PROVIDER=nvidia
MODEL_TEMPERATURE=0.4
MAX_TOKENS=2500

# Your LLM API Keys
NVIDIA_API_KEY=nvapi-xxxxx
# OPENAI_API_KEY=sk-xxxxx
# GROQ_API_KEY=gsk_xxxxx

# Scheduler Settings
SCHEDULE_TIME=08:00      # Daily run time (HH:MM)
DAYS_THRESHOLD=2          # Look back N days
MAX_EMAIL_RESULTS=10      # Max emails to fetch
RETRY_COUNT=3             # Retry on failure
RETRY_DELAY=60            # Seconds between retries

# Email Settings (for sending summaries)
MY_EMAIL=your@email.com
EMAIL_HOST_USER=your@email.com
EMAIL_HOST_PASSWORD=your_app_password

# Redis (Upstash)
REDIS_URL=rediss://xxxxx
```

### 3. First-Time OAuth Setup (Required)
Before running in Docker, you need to authenticate with Google. Run this **once** locally:

```bash
# Option A: Using the setup script (easiest)
cd /path/to/Morning-Mailer
./oauth_setup.sh

# Option B: Using IPython
cd /path/to/Morning-Mailer
uv run ipython
# In IPython:
from modules.fetch_emails import get_gmail_service
get_gmail_service()

# Follow the prompts - it will show a URL to visit in your browser
# After login, you'll be asked to enter the authorization code
# Token will be saved to gauth/token.json

# Option C: Using Python directly
cd /path/to/Morning-Mailer
uv run python -c "from modules.fetch_emails import get_gmail_service; get_gmail_service()"
```

This saves the OAuth token locally. The token will persist in Docker via volume mount.

### 4. Run
```bash
# Start the container
docker compose up -d

# Check logs
docker compose logs -f huey

# Manually trigger a run
docker compose exec huey python -c "from tasks import daily_email_summary; daily_email_summary.enqueue()"
```

## Project Structure

```
Morning-Mailer/
├── tasks.py                    # Main scheduler & task logic
├── modules/
│   ├── fetch_emails.py        # Gmail API integration
│   ├── agent_mod.py           # LLM wrapper
│   ├── agent_utils.py         # LLM factory
│   ├── prompt.py              # AI summarization prompt
│   ├── logger.py              # Logging
│   ├── generics.py            # Utility functions
│   ├── ipython_startup.py     # IPython magic functions
│   └── ipython_config.py      # IPython configuration
├── gauth/                     # OAuth credentials (your files)
│   ├── client_secret.json
│   └── token.json
├── .env                       # Configuration
├── Dockerfile                 # Container image
└── compose.yml               # Docker orchestration
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `SCHEDULE_TIME` | Daily run time (HH:MM) | 08:00 |
| `DAYS_THRESHOLD` | Days to look back | 2 |
| `MAX_EMAIL_RESULTS` | Max emails to fetch | 10 |
| `RETRY_COUNT` | Failed attempt retries | 3 |
| `RETRY_DELAY` | Seconds between retries | 60 |
| `MODEL_PROVIDER` | LLM: nvidia/openai/groq/openrouter/google | nvidia |
| `MODEL_TEMPERATURE` | AI creativity (0-1) | 0.4 |
| `MY_EMAIL` | Recipient for daily summary | - |
| `EMAIL_HOST_USER` | SMTP username (your email) | - |
| `EMAIL_HOST_PASSWORD` | SMTP password (app password) | - |

## Scheduling

The task runs automatically at `SCHEDULE_TIME` (e.g., 08:00 daily).

## IPython Magic Functions

Inside the container, use IPython for testing:

```bash
docker compose exec huey uv run ipython
```

Available magic functions:

| Command | Description |
|---------|-------------|
| `%daily_email_summary` | Enqueue the daily email fetch task |
| `%check_job_status <job_id>` | Check status of a Huey job |
| `%cls` | Clear the terminal screen |
| `%autoreload 2` | Auto-reload changed modules |

Example usage:
```python
# Enqueue a job
%daily_email_summary
# Output: <job_id>

# Check status
%check_job_status <job_id>
```

## Manual Testing

```bash
# Direct function call
docker compose exec huey python -c "
from tasks import fetch_emails_with_retry, summarize_emails

result = fetch_emails_with_retry()
if result['emails']:
    summary = summarize_emails(result['emails'])
    print(summary)
"

# Send test email
docker compose exec huey python -c "
from tasks import send_email
send_email('your@email.com', 'Test', 'Hello World')
"

# Via Huey task
docker compose exec huey python -c "from tasks import daily_email_summary; daily_email_summary()"
```

## Logs

View real-time logs:
```bash
docker compose logs -f huey
```

Sample output:
```
2026-05-09 08:00 | INFO | tasks | Starting daily email fetch (last 2 day(s))...
2026-05-09 08:00 | INFO | tasks | Fetching emails from 06:00:00 07:05:2026 to 08:00:00 09:05:2026
2026-05-09 08:00 | SUCCESS | tasks | Fetched 5 emails
2026-05-09 08:00 | INFO | [agent] | Initializing LLM: nvidia (temp: 0.4, tokens: 2500)
2026-05-09 08:00 | INFO | [agent] | Summarizing 5 emails...
2026-05-09 08:00 | SUCCESS | [agent] | Email summary generated

============================================================
EMAIL SUMMARY
============================================================
[HTML output with dark theme]
============================================================
2026-05-09 08:00 | INFO | tasks | Daily email fetch completed at 2026-05-09 08:00:00
2026-05-09 08:00 | INFO | tasks | Emailing the summary to your@email.com
```

## Troubleshooting

### No module named 'xxx'
```bash
# Rebuild the container
docker compose build --no-cache huey
docker compose up -d
```

### Gmail credentials not found
- Ensure `gauth/client_secret.json` exists
- Ensure `gauth/token.json` is present (generated on first run)

### Redis connection refused
- Check `REDIS_URL` in `.env`
- Ensure container can reach Upstash

### Email sending fails
- Check `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` in `.env`
- Use Gmail App Password (not your regular password)
- Enable 2FA on Google Account and create App Password

### First run - OAuth flow
- Run OAuth setup locally first (see Section 3 above):
  ```bash
  uv run ipython
  from modules.fetch_emails import get_gmail_service
  get_gmail_service()
  ```
- This saves the token to `gauth/token.json`
- Docker will use the mounted volume to access the token
- No browser needed in Docker - OAuth completes locally

## Tech Stack

- **Task Queue**: Huey (Redis-backed)
- **Gmail API**: google-api-python-client
- **LLM**: LangChain (NVIDIA, OpenAI, Groq, OpenRouter, Google)
- **Logging**: loguru
- **Email**: smtplib (SMTP)
- **Container**: Docker + Docker Compose

## License

MIT