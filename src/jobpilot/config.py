"""Application configuration using pydantic-settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """JobPilot configuration loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application & Server
    app_env: str = Field(default="development", description="Application environment")
    api_host: str = Field(default="0.0.0.0", description="API bind host")
    api_port: int = Field(default=8000, description="API bind port")
    base_url: str = Field(default="http://localhost:8000", description="Base public URL")
    log_level: str = Field(default="INFO", description="Log level")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/jobpilot",
        description="Async PostgreSQL connection string",
    )
    database_sync_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/jobpilot",
        description="Synchronous PostgreSQL connection string for migrations",
    )

    # Security / Encryption
    fernet_key: str = Field(
        default="wU918b0Bq_PsA5XEnvI6FmqVGRqZRXl5r42SyTjkpT4=",
        description="Fernet symmetric key for encrypting refresh tokens at rest",
    )

    # Telegram Bot
    telegram_bot_token: str = Field(default="", description="Telegram Bot API Token")
    telegram_webhook_url: str | None = Field(default=None, description="Optional webhook URL")

    # Google OAuth (Gmail read-only)
    google_client_id: str = Field(default="", description="Google OAuth Client ID")
    google_client_secret: str = Field(default="", description="Google OAuth Client Secret")
    google_redirect_uri: str = Field(
        default="http://localhost:8000/auth/google/callback",
        description="Google OAuth Redirect URI",
    )

    # LLM & Embeddings
    llm_provider: str = Field(
        default="gemini",
        description="LLM provider: 'gemini' or 'anthropic'",
    )
    gemini_api_key: str = Field(default="", description="Google Gemini API Key")
    anthropic_api_key: str = Field(default="", description="Anthropic API Key")
    llm_model: str = Field(
        default="gemini-2.0-flash",
        description="Default LLM model name (e.g. gemini-2.0-flash or claude-3-5-haiku-20241022)",
    )
    embeddings_dimension: int = Field(
        default=768,
        description="Vector dimension for embeddings (768 for Gemini, 1536 for OpenAI/Voyage)",
    )
    embeddings_api_key: str = Field(default="", description="Hosted Embeddings API Key")

    # Intervals (in seconds)
    gmail_poll_interval_seconds: int = Field(default=240, description="Gmail poll interval")
    reminder_tick_interval_seconds: int = Field(
        default=60, description="Reminder tick worker interval"
    )
    job_board_poll_interval_seconds: int = Field(
        default=300, description="Job boards poll interval"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached instance of application settings."""
    return Settings()
