from pydantic_settings import BaseSettings
from pydantic import computed_field


# =============================================================================
# CUSTOMIZE: Update PROJECT_NAME and PROJECT_TAGLINE for your app
# =============================================================================
class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # App branding
    PROJECT_NAME: str = "My App"
    PROJECT_TAGLINE: str = "Built with FastAPI + Google OAuth"

    # Google OAuth2 (required) - Get from Google Cloud Console
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str

    # App URLs
    APP_BASE_URL: str = "http://127.0.0.1:8000"
    GOOGLE_REDIRECT_URI: str = "http://127.0.0.1:8000/auth/callback"

    # Security keys (generate with: uv run python -c "import secrets; print(secrets.token_hex(32))")
    SECRET_KEY: str = "change-me"
    JWT_SECRET_KEY: str = "change-me"

    # JWT settings
    JWT_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_DAYS: int = 7

    @computed_field
    @property
    def GOOGLE_AUTHORIZED_ORIGIN(self) -> str:
        return self.APP_BASE_URL


settings = Settings()
