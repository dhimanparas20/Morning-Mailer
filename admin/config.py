import os
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
TOKEN_DIR = BASE_DIR / "gauth" / "tokens"
CLIENT_SECRET_WEB_PATH = BASE_DIR / "gauth" / "client_secret_web.json"
CLIENT_SECRET_PATH = BASE_DIR / "gauth" / "client_secret.json"


class Settings(BaseSettings):
    SECRET_KEY: str = "morning-mailer-admin-secret-change-in-production"
    SESSION_EXPIRE_MINUTES: int = 480
    REDIS_URL: str = "redis://localhost:6379/0"
    OAUTH_CALLBACK_URL: str = "http://localhost:8000/oauth/callback"
    WAHA_API_URL: str = "http://waha:3000"
    WAHA_API_KEY: str = ""
    WAHA_SESSION: str = "default"
    ADMIN_HOST: str = "0.0.0.0"
    ADMIN_PORT: int = 8000

    # Google OAuth (Admin Login)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    JWT_SECRET_KEY: str = "change-this-to-a-random-jwt-secret-key"
    ADMIN_EMAILS: str = "dhimanparas20@gmail.com"
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/callback"
    APP_BASE_URL: str = "http://localhost:8000"

    model_config = {"env_file": str(BASE_DIR / ".env"), "extra": "ignore"}

    @property
    def admin_email_set(self) -> set[str]:
        """Parse comma-separated ADMIN_EMAILS into a set of lowercase emails."""
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
