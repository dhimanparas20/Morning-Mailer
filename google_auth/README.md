# FastAPI Google Auth Template

A production-ready FastAPI template with Google OAuth 2.0, JWT authentication, token revocation, dark/light themes, and responsive UI.

---

## Step 1: Install Python and uv

This project uses [uv](https://docs.astral.sh/uv/) as the package manager.

```bash
# Install uv (macOS/Linux)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or with pip
pip install uv
```

You need **Python 3.11 or higher**. uv will auto-install it if missing.

---

## Step 2: Clone and Install Dependencies

```bash
# Clone the template
git clone <your-repo-url> my-app
cd my-app

# Install all dependencies
uv sync
```

---

## Step 3: Create Your Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Sign in with your Google account
3. Click **Select a Project** (top left) → **New Project**
4. Enter a project name (e.g., "My App") → Click **Create**
5. Go to **APIs & Services** → **OAuth consent screen**
6. Select **External** → Click **Create**
7. Fill in:
   - App name: Your app name
   - User support email: Your email
   - Developer contact: Your email
8. Click **Save and Continue** (skip scopes, test users)
9. Go to **APIs & Services** → **Credentials**
10. Click **+ Create Credentials** → **OAuth client ID**
11. Application type: **Web application**
12. Name: "My Web App"
13. Authorized redirect URIs: Add `http://127.0.0.1:8000/auth/callback`
14. Click **Create**
15. **Copy the Client ID and Client Secret**

---

## Step 4: Configure Environment Variables

```bash
# Create your .env file from the example
cp .env.example .env
```

Open `.env` and fill in your values:

```bash
# App Name (shows in browser tab and navbar)
PROJECT_NAME=My App
PROJECT_TAGLINE=My awesome app description

# Google OAuth (paste from Step 3)
GOOGLE_CLIENT_ID=123456789-abcdefg.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-secret-here

# App URLs (default for local development)
APP_BASE_URL=http://127.0.0.1:8000
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/auth/callback

# Security Keys (generate your own!)
SECRET_KEY=run-this-command-to-generate
JWT_SECRET_KEY=run-this-command-to-generate
```

**Generate secure random keys:**

```bash
# Run these in your terminal and paste the output into .env
uv run python -c "import secrets; print(secrets.token_hex(32))"
uv run python -c "import secrets; print(secrets.token_hex(32))"
```

Put one output as `SECRET_KEY` and the other as `JWT_SECRET_KEY`.

---

## Step 5: Run the Server

```bash
uv run uvicorn main:app --reload --port 8000
```

**Note:** The app will refuse to start if `SECRET_KEY` or `JWT_SECRET_KEY` are still "change-me". Generate real keys first.

Open your browser and go to: **http://127.0.0.1:8000**

---

## How It Works

### Authentication Flow

```
1. User clicks "Sign In with Google"
   ↓
2. Redirected to Google's login page
   ↓
3. User signs in with Google
   ↓
4. Google redirects back to /auth/callback
   ↓
5. Server creates JWT access + refresh tokens
   ↓
6. Tokens passed via httponly cookie (NOT URL)
   ↓
7. /auth/success reads cookie, sets localStorage, deletes cookie
   ↓
8. API calls include: Authorization: Bearer <token>
```

### Token Management

| Token | Purpose | Expiry |
|-------|---------|--------|
| Access Token | Access protected routes | 60 minutes |
| Refresh Token | Get new access tokens | 7 days |

### Token Revocation (Logout)

When you click "Sign Out", the server revokes the token using a JTI (JWT ID) system:

1. Each token gets a unique `jti` ID when created
2. On logout, the `jti` is added to a revocation list
3. All API calls check if the token's `jti` is revoked
4. Revoked tokens are rejected immediately

**Production note:** The revocation list is in-memory. For production, use Redis or a database.

---

## Security Features

This template includes production-ready security measures:

### Security Headers
- `X-Content-Type-Options: nosniff` - Prevents MIME type sniffing
- `X-Frame-Options: DENY` - Prevents clickjacking
- `X-XSS-Protection: 1; mode=block` - XSS protection
- `Referrer-Policy: strict-origin-when-cross-origin` - Controls referrer info
- `Permissions-Policy: camera=(), microphone=(), geolocation=()` - Restricts browser features
- `Content-Security-Policy` - Controls allowed resources
- `Strict-Transport-Security` - HSTS (HTTPS only)

### Rate Limiting
- 30 requests per 60 seconds per IP
- Returns 429 status code when exceeded

### Token Security
- Tokens transferred via httponly cookie (not URL params)
- Frontend validates token expiry before API calls
- Refresh tokens rotate on use (old token revoked)
- App refuses to start with default secret keys

### Input Validation
- Error parameters validated against whitelist
- All user data properly escaped in templates

---

## Project Structure

```
.
├── main.py                     # Entry point
├── google_auth/                # All auth-related code
│   ├── __init__.py
│   ├── app/
│   │   ├── __init__.py
│   │   ├── api.py              # API endpoints (/api/me, /api/refresh)
│   │   ├── auth.py             # Google OAuth routes
│   │   ├── config.py           # Settings (pydantic-settings)
│   │   └── dependencies.py     # JWT utilities
│   ├── static/
│   │   ├── css/                # Stylesheets
│   │   └── js/                 # Client scripts
│   ├── templates/
│   │   ├── pages/              # Page templates
│   │   │   ├── home.html       # Landing page
│   │   │   ├── login.html      # Sign in page
│   │   │   ├── dashboard.html  # User dashboard
│   │   │   └── auth_success.html
│   │   ├── partials/           # Reusable components
│   │   │   ├── navbar.html
│   │   │   └── footer.html
│   │   └── base.html           # Base template
│   ├── AGENTS.md               # AI assistant rules
│   └── README.md               # This file
├── .env                        # Your config (git-ignored)
├── .env.example                # Environment template
└── pyproject.toml              # Dependencies
```

---

## Customization Guide

### Change Project Name and Branding

Edit `app/config.py` or set in `.env`:

```bash
PROJECT_NAME=Your App Name
PROJECT_TAGLINE=Your tagline here
```

### Add a New Page

1. Create `templates/pages/your-page.html`:

```html
{% extends "base.html" %}

{% block title %}Your Page - {{ project_name }}{% endblock %}

{% block content %}
<h1>Your Custom Page</h1>
<!-- Your content here -->
{% endblock %}
```

2. Add a route in `main.py`:

```python
@app.get("/your-page", response_class=HTMLResponse)
async def your_page(request: Request):
    return templates.TemplateResponse(
        request, "pages/your-page.html", _ctx(request)
    )
```

### Customize the Dashboard

Edit `templates/pages/dashboard.html`. Look for the `CUSTOMIZE` comment to add your content.

### Add API Endpoints

Edit `app/api.py`:

```python
@router.get("/your-endpoint")
async def your_endpoint(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials
    payload = verify_token(token, token_type="access")
    # Your logic here
    return {"data": "your response"}
```

---

## API Reference

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/` | No | Landing page |
| GET | `/login` | No | Sign in page |
| GET | `/dashboard` | Yes | Dashboard (requires JWT) |
| GET | `/auth/login` | No | Start Google OAuth |
| GET | `/auth/callback` | No | Google OAuth callback |
| POST | `/auth/logout` | Yes | Revoke current token |
| GET | `/api/me` | Yes | Get current user info |
| POST | `/api/refresh` | Yes | Refresh access token |

---

## Testing APIs with Postman

### Prerequisites

1. Start the server: `uv run uvicorn main:app --reload --port 8000`
2. Get a token: Login via browser → Open DevTools → Console → Run:
   ```javascript
   localStorage.getItem("access_token")
   ```
3. Copy the token for use in Postman.

### POST /auth/logout

**Purpose:** Revoke the current access token (server-side invalidation)

| Setting | Value |
|---------|-------|
| Method | `POST` |
| URL | `http://127.0.0.1:8000/auth/logout` |

**Headers:**
| Key | Value |
|-----|-------|
| Authorization | `Bearer YOUR_ACCESS_TOKEN` |

**Response (200):**
```json
{
  "message": "Logged out"
}
```

**After logout:** The token is revoked. Any subsequent API calls with this token will return 401.

---

### GET /api/me

**Purpose:** Get current authenticated user info

| Setting | Value |
|---------|-------|
| Method | `GET` |
| URL | `http://127.0.0.1:8000/api/me` |

**Headers:**
| Key | Value |
|-----|-------|
| Authorization | `Bearer YOUR_ACCESS_TOKEN` |

**Response (200):**
```json
{
  "id": "108822879410220819921",
  "email": "user@gmail.com",
  "name": "John Doe",
  "picture": "https://lh3.googleusercontent.com/..."
}
```

**Error (401):**
```json
{
  "detail": "Could not validate credentials"
}
```

---

### POST /api/refresh

**Purpose:** Get a new access token using refresh token (with rotation - old refresh token is revoked)

| Setting | Value |
|---------|-------|
| Method | `POST` |
| URL | `http://127.0.0.1:8000/api/refresh` |

**Headers:**
| Key | Value |
|-----|-------|
| Authorization | `Bearer YOUR_REFRESH_TOKEN` |

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

**Note:** The old refresh token is revoked. Use the new `refresh_token` for subsequent refresh calls.

---

### Postman Setup (Step-by-Step)

1. **Create a new Collection** called "FastAPI Google Auth"

2. **Add environment variables:**
   - `base_url`: `http://127.0.0.1:8000`
   - `access_token`: (paste your token)
   - `refresh_token`: (paste your refresh token)

3. **For each request:**
   - Go to **Authorization** tab
   - Type: **Bearer Token**
   - Token: `{{access_token}}` or `{{refresh_token}}`

4. **Save responses** to reuse tokens:
   - After `/api/refresh`, use Tests tab:
     ```javascript
     var response = pm.response.json();
     pm.environment.set("access_token", response.access_token);
     pm.environment.set("refresh_token", response.refresh_token);
     ```

---

## Testing APIs with cURL

### Get Access Token (from browser)

```bash
# Open browser console at http://127.0.0.1:8000/dashboard
# Run:
localStorage.getItem("access_token")

# Or get both tokens:
JSON.stringify({
  access: localStorage.getItem("access_token"),
  refresh: localStorage.getItem("refresh_token")
})
```

### GET /api/me

```bash
curl -X GET "http://127.0.0.1:8000/api/me" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Example:**
```bash
curl -X GET "http://127.0.0.1:8000/api/me" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Response:**
```json
{"id":"108822879410220819921","email":"user@gmail.com","name":"John Doe","picture":"https://lh3.googleusercontent.com/..."}
```

---

### POST /api/refresh

```bash
curl -X POST "http://127.0.0.1:8000/api/refresh" \
  -H "Authorization: Bearer YOUR_REFRESH_TOKEN"
```

**Response:**
```json
{"access_token":"eyJhbGciOiJIUzI1NiIs...","refresh_token":"eyJhbGciOiJIUzI1NiIs...","token_type":"bearer"}
```

---

### POST /auth/logout

```bash
curl -X POST "http://127.0.0.1:8000/auth/logout" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Response:**
```json
{"message":"Logged out"}
```

**Verify revocation** - try using the same token again:
```bash
curl -X GET "http://127.0.0.1:8000/api/me" \
  -H "Authorization: Bearer YOUR_REVOKED_TOKEN"
```

**Response (401):**
```json
{"detail":"Token has been revoked"}
```

---

### cURL One-Liner Workflow

```bash
# 1. Login via browser, then extract token:
TOKEN=$(curl -s "http://127.0.0.1:8000/dashboard" > /dev/null && echo "PASTE_TOKEN_HERE")

# 2. Get user info:
curl -s -X GET "http://127.0.0.1:8000/api/me" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool

# 3. Refresh token (save new tokens):
curl -s -X POST "http://127.0.0.1:8000/api/refresh" \
  -H "Authorization: Bearer $REFRESH_TOKEN" | python -m json.tool

# 4. Logout (revoke):
curl -s -X POST "http://127.0.0.1:8000/auth/logout" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

---

### Common cURL Flags

| Flag | Purpose |
|------|---------|
| `-X GET/POST` | HTTP method |
| `-H "Key: Value"` | Add header |
| `-d '{"key":"val"}'` | Send JSON body |
| `-s` | Silent mode (no progress) |
| `-v` | Verbose (see headers) |
| `\` | Line continuation |

**Verbose mode** (see request/response headers):
```bash
curl -v -X GET "http://127.0.0.1:8000/api/me" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Database Integration (Production)

This template stores user data in JWT tokens (stateless). For production, you should persist user data:

### 1. Add a database driver

```bash
# PostgreSQL (recommended for production)
uv add sqlalchemy asyncpg

# Or SQLite for simpler setups
uv add sqlalchemy aiosqlite
```

### 2. Create user model in `app/models.py`

```python
from sqlalchemy import Column, String
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)  # Google's sub ID
    email = Column(String, unique=True, index=True)
    name = Column(String)
    picture = Column(String)
```

### 3. Save user on login in `app/auth.py` callback

```python
# After getting user_info from Google
from app.models import User, db

user = db.query(User).filter(User.id == user_data["sub"]).first()
if not user:
    user = User(**user_data)
    db.add(user)
    db.commit()
```

### 4. Store revoked tokens in database or Redis

```python
# Example with Redis (recommended)
import redis
revoked = redis.Redis()

def revoke_token(jti: str):
    revoked.setex(f"revoked:{jti}", 86400 * 7, "1")  # 7 days

def is_token_revoked(jti: str) -> bool:
    return revoked.exists(f"revoked:{jti}")
```

---

## Production Notes

### In-Memory Limitations

This template uses in-memory storage for development simplicity. For production:

| Component | Development | Production |
|-----------|-------------|------------|
| Rate Limiting | In-memory dict | Redis + slowapi |
| Token Revocation | In-memory set | Redis or PostgreSQL |
| Token Storage | localStorage | httpOnly cookies (recommended) |

### Switching to Redis

```bash
uv add redis slowapi
```

Example Redis-backed revocation:
```python
import redis
revoked = redis.Redis(host="localhost", port=6379, db=0)

def revoke_token(jti: str):
    revoked.setex(f"revoked:{jti}", 86400 * 7, "1")  # 7 days TTL

def is_token_revoked(jti: str) -> bool:
    return revoked.exists(f"revoked:{jti}")
```

### httpOnly Cookies vs localStorage

| Storage | Pros | Cons |
|---------|------|------|
| localStorage | Simple, works offline | Vulnerable to XSS |
| httpOnly cookie | Immune to XSS | Needs CSRF protection, more complex |

For higher security, consider using httpOnly cookies with CSRF tokens instead of localStorage.

### Database Integration

Currently, user data is stored in JWT tokens (stateless). For persistent user storage:

```bash
uv add sqlalchemy asyncpg  # PostgreSQL
# or
uv add sqlalchemy aiosqlite  # SQLite
```

See the Database Integration section below for implementation details.

---

## Tech Stack

- **FastAPI** - Modern async Python web framework
- **Authlib** - OAuth 2.0 client for Google login
- **PyJWT (jose)** - JWT token creation and verification
- **Pydantic Settings** - Environment variable management
- **Jinja2** - HTML template engine
- **uv** - Fast Python package manager

---

## License

MIT
