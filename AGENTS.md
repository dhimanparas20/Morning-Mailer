# Morning Mailer - Codebase Documentation for AI Agents

## Project Overview

Morning Mailer is an AI-powered email summarization system that automatically fetches emails from Gmail at scheduled times, generates concise HTML summaries using Large Language Models, and emails them to the user.

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│  Gmail API     │────▶│ Huey Worker  │────▶│  LLM (NVIDIA/
│  (Email Fetch) │     │ (Scheduler)  │     │  OpenAI/    │
└─────────────────┘     └──────────────┘     │  Groq)       │
                                              └─────────────┘
         │                      │
         │              ┌──────┴──────┐
         │              │   Redis      │
         │              │ (Upstash)    │
         │              └─────────────┘
         ▼
   ┌──────────────────────────────────────┐
   │         Email Summary Output          │
   │  - HTML formatted with dark theme    │
   │  - Sent via SMTP to MY_EMAIL         │
   └──────────────────────────────────────┘
```

## Core Components

### 1. tasks.py - Task Scheduler
- **Purpose**: Main entry point for scheduled email fetching, summarization, and sending
- **Key Functions**:
  - `get_job_status(job_id)`: Check status of a Huey job by ID
  - `fetch_emails_with_retry()`: Fetches emails with configurable retry logic
  - `summarize_emails(emails)`: Uses LLM to summarize fetched emails
  - `send_email(to, subject, body, is_html)`: Sends email via SMTP
  - `daily_email_summary()`: Huey periodic task - runs at SCHEDULE_TIME
  - `send_email_task()`: Huey task for async email sending

- **Configuration (from .env)**:
  - `RETRY_COUNT`: Number of retry attempts (default: 3)
  - `RETRY_DELAY`: Seconds between retries (default: 60)
  - `MAX_EMAIL_RESULTS`: Max emails to fetch (default: 10)
  - `SCHEDULE_TIME`: Daily run time in HH:MM (default: 08:00)
  - `DAYS_THRESHOLD`: Days to look back (default: 1)
  - `MY_EMAIL`: Recipient email for summary
  - `EMAIL_HOST_USER`: SMTP username
  - `EMAIL_HOST_PASSWORD`: SMTP password (app password)

### 2. modules/fetch_emails.py - Gmail Integration
- **Purpose**: Handles all Gmail API interactions
- **Key Functions**:
  - `get_gmail_service()`: Initializes Gmail API client with OAuth
  - `fetch_emails()`: Main API to retrieve emails with filtering
  - `parse_date()`: Parses various email date formats
  - `clean_text()`: Sanitizes email content
  - `extract_plain_text()`: Extracts text from email body

- **OAuth Flow**:
  1. Checks for existing token in `gauth/token.json`
  2. If valid, uses it directly
  3. If expired, attempts refresh
  4. If no valid token, requires `gauth/client_secret.json`

- **Email Filtering**:
  - `date_from`: ISO datetime string
  - `date_to`: ISO datetime string
  - `sender`: Filter by sender email
  - `query`: Raw Gmail search query
  - `has_attachments`: Boolean filter

### 3. modules/agent_mod.py - LLM Integration
- **Purpose**: Wrapper for LLM summarization
- **Key Functions**:
  - `init()`: Initializes LLM from config
  - `summarize_emails(emails, prompt)`: Generates summary

- **Supported Providers**:
  - `nvidia` (default): NVIDIA NIM endpoints
  - `openai`: OpenAI models
  - `groq`: Groq models
  - `openrouter`: OpenRouter aggregation
  - `google`: Google Gemini

### 4. modules/prompt.py - Summarization Prompt
- **Purpose**: Defines how LLM should summarize emails (outputs HTML)
- **Categories**:
  - Critical: Payment failures, security alerts, deployment issues
  - Important: Project updates, service warnings, notifications
  - Informational: Status updates, digests
  - Ignored: Marketing, promotions, newsletters
- **Output**: Dark-themed HTML with inline CSS for email compatibility

### 5. modules/agent_utils.py - LLM Factory
- **Purpose**: Creates LLM instances dynamically
- **Function**: `create_llm()` - Factory function supporting multiple providers
- **Model Registry**: Maps provider names to LangChain classes

### 6. modules/logger.py - Logging
- **Purpose**: Consistent logging across application
- **Features**: Colored output, timestamps, structured logging

### 7. modules/generics.py - Utility Functions
- `get_timestamp()`: Unix epoch timestamp
- `format_timestamp()`: Convert to human-readable HH:MM:SS DD:MM:YYYY
- `parse_datetime()`: ISO string to timestamp
- `utc_to_local()`: Convert UTC to local timezone

### 8. modules/ipython_startup.py - IPython Magic Functions
- **Purpose**: Custom IPython commands for easy testing
- **Magic Functions**:
  - `%daily_email_summary`: Enqueue the daily email fetch task
  - `%check_job_status <job_id>`: Check status of a Huey job
  - `%cls`: Clear the terminal screen
  - `%autoreload 2`: Auto-reload changed modules

## Data Flow

```
1. Huey scheduler triggers at SCHEDULE_TIME
          │
          ▼
2. daily_email_summary() called
          │
          ▼
3. fetch_emails_with_retry():
   - Calculate date_from = now - DAYS_THRESHOLD
   - date_to = now
   - Call fetch_emails() with date filters
   - Retry up to RETRY_COUNT times on failure
          │
          ▼
4. fetch_emails():
   - Get Gmail service (handle OAuth)
   - List messages with query
   - Get each message detail (full format)
   - Filter by date range
   - Return: {success, count, emails[], filters_applied}
          │
          ▼
5. summarize_emails(emails):
   - Use pre-initialized MCPAgentModule
   - Call agent.summarize_emails(emails, SYSTEM_PROMPT)
          │
          ▼
6. agent.summarize_emails():
   - Build prompt with SYSTEM_PROMPT + email JSON
   - Invoke LLM with HumanMessage
   - Return: formatted HTML summary string
          │
          ▼
7. Print summary to console
          │
          ▼
8. send_email_task():
   - Async task to send email via SMTP
   - Uses EMAIL_HOST_USER/PASSWORD credentials
   - Sends HTML to MY_EMAIL
          │
          ▼
9. Return status: {date, time, emails_fetched, emails_summarized}
```

## File Structure

```
Morning-Mailer/
├── tasks.py              # Huey task scheduler & main logic
├── modules/
│   ├── __init__.py       # Module exports
│   ├── fetch_emails.py   # Gmail API integration
│   ├── agent_mod.py      # LLM summarization wrapper
│   ├── agent_utils.py     # LLM factory function
│   ├── prompt.py         # SYSTEM_PROMPT for summarization
│   ├── logger.py         # Logging utilities
│   ├── generics.py       # Utility functions
│   ├── ipython_startup.py # IPython magic functions
│   └── ipython_config.py  # IPython configuration
├── gauth/
│   ├── client_secret.json # OAuth credentials (your config)
│   └── token.json          # OAuth token (auto-generated)
├── .env                   # Environment variables
├── Dockerfile             # Container image definition
├── compose.yml            # Docker Compose orchestration
├── pyproject.toml         # Python dependencies
└── uv.lock                # Locked dependencies
```

## Key Configuration

### .env Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `MODEL_PROVIDER` | LLM provider (nvidia/openai/groq/openrouter/google) | nvidia |
| `NVIDIA_MODEL` | Model for NVIDIA | qwen/qwen3-next-80b-a3b-instruct |
| `OPENAI_MODEL` | Model for OpenAI | gpt-4o-mini |
| `MODEL_TEMPERATURE` | LLM creativity | 0.4 |
| `MAX_TOKENS` | Max response length | 2500 |
| `REDIS_URL` | Upstash Redis connection string | (your URL) |
| `SCHEDULE_TIME` | Daily run time | 08:00 |
| `DAYS_THRESHOLD` | Look back period | 2 |
| `MAX_EMAIL_RESULTS` | Max emails to fetch | 10 |
| `RETRY_COUNT` | Retry attempts | 3 |
| `RETRY_DELAY` | Seconds between retries | 60 |
| `MY_EMAIL` | Recipient for daily summary | (your email) |
| `EMAIL_HOST_USER` | SMTP username | (your email) |
| `EMAIL_HOST_PASSWORD` | SMTP app password | (app password) |

## Huey Task Scheduling

```python
# Daily at specific time
@huey.periodic_task(crontab(hour=8, minute=0))

# Every 2 minutes (for testing)
@huey.periodic_task(crontab(minute='*/2'))

# Every hour
@huey.periodic_task(crontab(hour='*'))
```

## IPython Magic Functions

When running `uv run ipython` inside the container, you have access to:

| Magic | Usage | Description |
|-------|-------|-------------|
| `%daily_email_summary` | `%daily_email_summary` | Enqueue the daily email fetch task |
| `%check_job_status` | `%check_job_status <job_id>` | Check job status by ID |
| `%cls` | `%cls` | Clear terminal screen |
| `%autoreload` | `%autoreload 2` | Auto-reload changed modules |

## Adding New Features

### To add a new LLM provider:
1. Add entry to `MODEL_REGISTRY` in `modules/agent_utils.py`
2. Ensure langchain package is in `pyproject.toml`
3. Update `.env` with provider API key

### To modify email filtering:
- Edit `fetch_emails()` in `modules/fetch_emails.py`
- Add new parameters to function signature
- Pass through from `tasks.py`

### To change summary format:
- Edit `SYSTEM_PROMPT` in `modules/prompt.py`
- LLM will follow new instructions on next run

### To add new email recipient:
- Update `MY_EMAIL` in `.env`
- Or call `send_email()` directly with different recipients

## Common Tasks

### Run manually in Docker:
```bash
docker compose exec huey python -c "from tasks import daily_email_summary; daily_email_summary.enqueue()"
```

### Check Huey worker logs:
```bash
docker compose logs -f huey
```

### Test in IPython:
```bash
docker compose exec huey uv run ipython
```

### Check job status (in IPython):
```python
# Enqueue a job
%daily_email_summary
# Output: <job_id>

# Check status
%check_job_status <job_id>
```

### Send test email:
```python
from tasks import send_email
send_email('test@example.com', 'Test Subject', 'Hello World!')
```

## Dependencies

- **huey**: Task queue & scheduler
- **google-api-python-client**: Gmail API
- **langchain-nvidia-ai-endpoints**: NVIDIA LLM
- **langchain-openai**: OpenAI LLM
- **langchain-groq**: Groq LLM
- **langchain-google-genai**: Google Gemini
- **loguru**: Logging
- **rich**: Terminal formatting
- **redis**: Task queue backend (Upstash)