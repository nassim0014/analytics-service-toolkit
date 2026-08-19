from typer.testing import CliRunner

from astk import cli as cli_module
from astk.alerts import AlertResult

runner = CliRunner()


def test_doctor_skips_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

    result = runner.invoke(cli_module.app, ["doctor"])

    assert result.exit_code == 0
    assert result.stdout.count("skipped") == 2


def test_doctor_reports_ok_when_healthy(monkeypatch):
    monkeypatch.setattr(cli_module, "healthcheck", lambda engine: True)
    monkeypatch.setattr(cli_module, "make_engine", lambda url: object())

    class _OkNotifier:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, alert):
            return AlertResult(ok=True, attempts=1)

    monkeypatch.setattr(cli_module, "SlackNotifier", _OkNotifier)

    result = runner.invoke(
        cli_module.app,
        ["doctor", "--database-url", "postgresql://x/db", "--slack-webhook-url", "https://hooks.slack.com/x"],
    )

    assert result.exit_code == 0
    assert "database   ok" in result.stdout
    assert "slack      ok" in result.stdout


def test_doctor_reports_fail_and_nonzero_exit(monkeypatch):
    monkeypatch.setattr(cli_module, "healthcheck", lambda engine: False)
    monkeypatch.setattr(cli_module, "make_engine", lambda url: object())

    result = runner.invoke(cli_module.app, ["doctor", "--database-url", "postgresql://x/db"])

    assert result.exit_code == 1
    assert "FAIL" in result.stdout


def test_alert_command_uses_console_when_no_webhook():
    result = runner.invoke(cli_module.app, ["alert", "Test title", "Test body"])

    assert result.exit_code == 0
    assert "ok=True" in result.stdout


def test_version_command_prints_version():
    from astk import __version__

    result = runner.invoke(cli_module.app, ["version"])

    assert result.exit_code == 0
    assert __version__ in result.stdout
