import pytest

from astk.settings import BaseServiceSettings, SettingsError, load_settings


class DemoSettings(BaseServiceSettings):
    api_key: str


def test_missing_required_var_raises_readable_error(monkeypatch, tmp_path):
    monkeypatch.delenv("API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("APP_NAME=demo\n")

    with pytest.raises(SettingsError) as exc_info:
        load_settings(DemoSettings, env_file=str(env_file))

    assert "api_key" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, Exception)


def test_env_file_values_are_loaded(monkeypatch, tmp_path):
    monkeypatch.delenv("API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("API_KEY=secret123\nAPP_NAME=demo\nENV=prod\n")

    settings = load_settings(DemoSettings, env_file=str(env_file))

    assert settings.api_key == "secret123"
    assert settings.app_name == "demo"
    assert settings.env == "prod"


def test_invalid_value_is_reported(monkeypatch, tmp_path):
    monkeypatch.delenv("API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("API_KEY=secret123\nENV=not-a-real-env\n")

    with pytest.raises(SettingsError) as exc_info:
        load_settings(DemoSettings, env_file=str(env_file))

    assert "env" in str(exc_info.value)


def test_secrets_redacted_in_repr(monkeypatch, tmp_path):
    monkeypatch.delenv("API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "API_KEY=secret123\n"
        "SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T000/B000/XXXXXXXX\n"
        "DATABASE_URL=postgresql://appuser:hunter2@localhost:5432/db\n"
    )

    settings = load_settings(DemoSettings, env_file=str(env_file))
    rendered = repr(settings)

    assert "hunter2" not in rendered
    assert "XXXXXXXX" not in rendered
    assert "appuser" in rendered  # username isn't secret, stays readable
    assert "***" in rendered


class _WithConns(BaseServiceSettings):
    pass


def test_slack_webhook_accessor_unwraps_the_secret(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    s = _WithConns(slack_webhook_url="https://hooks.slack.com/x")

    # The trap the accessor exists to avoid: str() on a pydantic SecretStr is the mask,
    # not the URL. This assertion documents pydantic's behaviour and holds on any version.
    assert str(s.slack_webhook_url) == "**********"

    assert s.slack_webhook() == "https://hooks.slack.com/x"
    assert s.slack_webhook() != "**********"


def test_slack_webhook_accessor_is_none_when_unset(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert _WithConns().slack_webhook() is None


def test_dsn_accessor_returns_a_plain_connection_string(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = _WithConns(database_url="postgresql://appuser:hunter2@localhost:5432/db")
    assert s.dsn() == "postgresql://appuser:hunter2@localhost:5432/db"


def test_dsn_accessor_raises_readable_error_when_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SettingsError) as exc_info:
        _WithConns().dsn()
    message = str(exc_info.value)
    assert "database_url" in message or "DATABASE_URL" in message
    assert message != "None"


def test_database_url_accepts_sqlite(monkeypatch):
    # SQLite must be accepted: services test on it and astk.db is SQLite-safe.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = _WithConns(database_url="sqlite:////tmp/app.db")
    assert s.dsn() == "sqlite:////tmp/app.db"


def test_database_url_still_validates_a_bad_postgres_url(monkeypatch):
    from pydantic import ValidationError

    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        _WithConns(database_url="postgresql://")  # no host -> invalid
