"""Unit tests for configuration loading."""

from jobpilot.config import Settings, get_settings


def test_default_settings() -> None:
    """Test that default settings load with reasonable defaults."""
    settings = Settings()
    assert settings.app_env in ("development", "production", "test")
    assert settings.api_port == 8000
    assert settings.embeddings_dimension == 1536
    assert settings.reminder_tick_interval_seconds == 60
    assert "postgresql" in settings.database_url


def test_get_settings_cached() -> None:
    """Test that get_settings() returns a cached singleton."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
