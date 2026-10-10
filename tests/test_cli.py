import json

import pandas as pd
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


def test_query_command_prints_table_by_default(monkeypatch):
    monkeypatch.setattr(cli_module, "make_engine", lambda url: object())
    monkeypatch.setattr(cli_module, "fetch_df", lambda engine, sql: pd.DataFrame({"a": [1, 2]}))

    result = runner.invoke(cli_module.app, ["query", "SELECT 1", "--database-url", "postgresql://x/db"])

    assert result.exit_code == 0
    assert "a" in result.stdout
    assert "1" in result.stdout
    assert "2" in result.stdout


def test_query_command_json_format(monkeypatch):
    monkeypatch.setattr(cli_module, "make_engine", lambda url: object())
    monkeypatch.setattr(cli_module, "fetch_df", lambda engine, sql: pd.DataFrame({"a": [1, 2]}))

    result = runner.invoke(
        cli_module.app,
        ["query", "SELECT 1", "--database-url", "postgresql://x/db", "--format", "json"],
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == '[{"a":1},{"a":2}]'


def test_query_command_csv_format(monkeypatch):
    monkeypatch.setattr(cli_module, "make_engine", lambda url: object())
    monkeypatch.setattr(cli_module, "fetch_df", lambda engine, sql: pd.DataFrame({"a": [1, 2]}))

    result = runner.invoke(
        cli_module.app,
        ["query", "SELECT 1", "--database-url", "postgresql://x/db", "--format", "csv"],
    )

    assert result.exit_code == 0
    assert result.stdout.startswith("a\n1\n2\n")


def test_version_command_prints_version():
    from astk import __version__

    result = runner.invoke(cli_module.app, ["version"])

    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_demo_runs_with_nothing_configured(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli_module.app, ["demo"])

    assert result.exit_code == 0
    assert "database_url='sqlite:///:memory:'" in result.stdout
    assert "healthcheck: ok" in result.stdout


def test_demo_redacts_the_slack_secret(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli_module.app, ["demo"])

    assert result.exit_code == 0
    assert "slack_webhook_url='***'" in result.stdout
    # the real demo webhook string never appears unredacted anywhere in the output
    assert "hooks.slack.com/services/DEMO" not in result.stdout


def test_demo_writes_back_the_same_row_count_it_wrote(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli_module.app, ["demo"])

    assert result.exit_code == 0
    assert "wrote 3 rows" in result.stdout
    assert "read 3 rows" in result.stdout


def test_demo_dedup_suppresses_the_second_call_on_the_same_key(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli_module.app, ["demo"])

    assert result.exit_code == 0
    assert "-> True   (first call, accepted)" in result.stdout
    assert "-> False  (second call, same key)" in result.stdout


def test_demo_json_flag_writes_a_machine_readable_summary(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    out_path = tmp_path / "summary.json"

    result = runner.invoke(cli_module.app, ["demo", "--json", str(out_path)])

    assert result.exit_code == 0
    assert out_path.exists()
    summary = json.loads(out_path.read_text())
    assert summary["settings"]["slack_webhook_url"] == "***"
    assert summary["database"] == {"wrote": 3, "read": 3, "healthcheck": True}
    assert summary["dedup"] == {"first": True, "second": False}
    assert summary["alert"]["ok"] is True


def test_demo_runs_twice_in_the_same_process_without_error(monkeypatch, tmp_path):
    # make_engine caches one Engine per URL, and the in-memory sqlite URL is
    # identical across invocations - this is the regression the DROP TABLE
    # guards against.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    first = runner.invoke(cli_module.app, ["demo"])
    second = runner.invoke(cli_module.app, ["demo"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "wrote 3 rows" in second.stdout
