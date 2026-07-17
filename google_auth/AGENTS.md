# AGENTS.md - AI Assistant Rules for This Codebase

> **READ THIS FIRST** before making any changes.

---

## Project Structure

```
.
├── main.py                     # Entry point - your app's main file
├── google_auth/                # All auth-related code
│   ├── __init__.py             # Makes it a Python package
│   ├── app/
│   │   ├── __init__.py
│   │   ├── api.py              # Protected API endpoints
│   │   ├── auth.py             # OAuth routes
│   │   ├── config.py           # Settings (pydantic-settings)
│   │   └── dependencies.py     # JWT utilities
│   ├── static/                 # CSS/JS files
│   │   ├── css/
│   │   └── js/
│   ├── templates/              # HTML templates
│   │   ├── base.html
│   │   ├── pages/
│   │   └── partials/
│   ├── AGENTS.md               # This file
│   └── README.md               # Detailed docs
├── .env.example                # Environment template
└── pyproject.toml              # Dependencies
```

---

## Import Rules

All imports from google_auth use the full path:

```python
# From main.py (root)
from google_auth.app.config import settings
from google_auth.app.api import router as api_router
from google_auth.app.auth import router as auth_router

# From within google_auth/app/*.py (internal imports)
from google_auth.app.config import settings
from google_auth.app.dependencies import verify_token
```

---

## File Paths

All file paths are relative to project root:

```python
# Static files (in main.py)
app.mount("/static", StaticFiles(directory="google_auth/static"), name="static")

# Templates (in main.py)
templates = Jinja2Templates(directory="google_auth/templates")

# .env file (in google_auth/app/config.py)
model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

---

## Entry Point

**File: `main.py`** (in project root)

```python
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from google_auth.app.config import settings
from google_auth.app.api import router as api_router
from google_auth.app.auth import router as auth_router

# Validate secrets on startup
if settings.SECRET_KEY == "change-me" or settings.JWT_SECRET_KEY == "change-me":
    raise RuntimeError("SECURITY: Change default secrets!")

app = FastAPI(title=settings.PROJECT_NAME, docs_url="/docs")

# Required by Authlib for OAuth state storage
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

# Middleware, routes, etc.
app.include_router(auth_router)
app.include_router(api_router)
```

Run with: `uv run main.py` or `uv run uvicorn main:app --reload`

---

## Configuration

**File: `google_auth/app/config.py`**

Uses pydantic-settings to auto-load `.env` from project root.

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
    
    PROJECT_NAME: str = "My App"
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    SECRET_KEY: str = "change-me"
    JWT_SECRET_KEY: str = "change-me"
    # ...

settings = Settings()
```

---

## Adding New Features

### Add a New Page

1. Create template: `google_auth/templates/pages/my-page.html`
2. Add route in `main.py`:

```python
@app.get("/my-page", response_class=HTMLResponse)
async def my_page(request: Request):
    return templates.TemplateResponse(
        request, "pages/my-page.html", _ctx(request)
    )
```

### Add a New API Endpoint

Add to `google_auth/app/api.py`:

```python
@router.get("/my-endpoint")
async def my_endpoint(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    payload = verify_token(credentials.credentials)
    return {"data": "value"}
```

---

## Security Rules

### Token Handling
- NEVER pass tokens via URL query params
- Use httponly cookies for OAuth callback
- Frontend stores in localStorage

### Secret Keys
- App refuses to start with default "change-me" values
- Generate with: `uv run python -c "import secrets; print(secrets.token_hex(32))"`

### Headers
Security headers are applied via middleware in main.py:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Content-Security-Policy
- Strict-Transport-Security (HTTPS only)

---

## Development Commands

```bash
# Run server
uv run main.py
# or
uv run uvicorn main:app --reload --port 8000

# Generate secret keys
uv run python -c "import secrets; print(secrets.token_hex(32))"

# Add dependency
uv add package-name
```

---

## Production Deployment

- Set `APP_BASE_URL` to your HTTPS domain
- Generate new SECRET_KEY and JWT_SECRET_KEY
- Replace in-memory revocation with Redis
- Add database for user storage
- Update Google OAuth redirect URIs

---

## Version Control

**Always commit:**
- `google_auth/` folder (entire auth module)
- `main.py`
- `.env.example`
- `pyproject.toml`

**Never commit:**
- `.env` (secrets)
- `.venv/`
- `__pycache__/`
