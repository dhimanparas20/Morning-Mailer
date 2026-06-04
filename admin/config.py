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
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "changeme"
    SECRET_KEY: str = "morning-mailer-admin-secret-change-in-production"
    SESSION_EXPIRE_MINUTES: int = 480
    REDIS_URL: str = "redis://localhost:6379/0"
    OAUTH_CALLBACK_URL: str = "http://localhost:8000/oauth/callback"
    WAHA_API_URL: str = "http://waha:3000"
    WAHA_API_KEY: str = ""
    WAHA_SESSION: str = "default"
    ADMIN_HOST: str = "0.0.0.0"
    ADMIN_PORT: int = 8000

    model_config = {"env_file": str(BASE_DIR / ".env"), "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
