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
