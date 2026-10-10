"""`astk` command-line entry point.

The flagship command is `astk doctor`: point it at a service's env vars and
it tells you, in one shot, whether the database and Slack webhook it depends
on are actually reachable - instead of finding out when the Airflow DAG
fails at 3am.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer
from sqlalchemy import text

from . import __version__
from .alerts import Alert, ConsoleNotifier, Deduplicator, SlackNotifier
from .db import fetch_df, healthcheck, make_engine, session_scope
from .logging import configure_logging
from .settings import BaseServiceSettings, load_settings

app = typer.Typer(help="astk - shared operational toolkit for this portfolio's Python services.")


@app.command()
def doctor(
    database_url: str | None = typer.Option(None, envvar="DATABASE_URL"),
    slack_webhook_url: str | None = typer.Option(None, envvar="SLACK_WEBHOOK_URL"),
) -> None:
    """Validate database connectivity and Slack webhook reachability."""
    rows: list[tuple[str, str, str]] = []

    if database_url:
        engine = make_engine(database_url)
        ok = healthcheck(engine)
        detail = database_url.split("@")[-1] if "@" in database_url else database_url
        rows.append(("database", "ok" if ok else "FAIL", detail))
    else:
        rows.append(("database", "skipped", "DATABASE_URL not set"))

    if slack_webhook_url:
        try:
            notifier = SlackNotifier(slack_webhook_url, dry_run=True)
        except ValueError as exc:
            rows.append(("slack", "FAIL", str(exc).splitlines()[0]))
        else:
            check_alert = Alert(title="astk doctor", body="connectivity check", severity="info")
            result = notifier.send(check_alert)
            rows.append(("slack", "ok" if result.ok else "FAIL", "dry-run"))
    else:
        rows.append(("slack", "skipped", "SLACK_WEBHOOK_URL not set"))

    typer.echo(f"{'CHECK':<10} {'STATUS':<8} DETAIL")
    failed = False
    for name, status, detail in rows:
        if status == "FAIL":
            failed = True
        typer.echo(f"{name:<10} {status:<8} {detail}")

    raise typer.Exit(code=1 if failed else 0)


@app.command()
def alert(
    title: str,
    body: str,
    severity: str = "info",
    webhook_url: str | None = typer.Option(None, "--webhook-url", envvar="SLACK_WEBHOOK_URL"),
    dry_run: bool = False,
) -> None:
    """Send an ad-hoc alert (Slack if --webhook-url/SLACK_WEBHOOK_URL is set, else console)."""
    notifier = SlackNotifier(webhook_url, dry_run=dry_run) if webhook_url else ConsoleNotifier()
    result = notifier.send(Alert(title=title, body=body, severity=severity))  # type: ignore[arg-type]
    typer.echo(f"ok={result.ok} attempts={result.attempts} error={result.error}")
    raise typer.Exit(code=0 if result.ok else 1)


@app.command()
def query(
    sql: str,
    database_url: str = typer.Option(..., envvar="DATABASE_URL"),
    output_format: str = typer.Option("table", "--format"),
) -> None:
    """Run a read query and print the result."""
    engine = make_engine(database_url)
    df = fetch_df(engine, sql)
    if output_format == "json":
        typer.echo(df.to_json(orient="records"))
    elif output_format == "csv":
        typer.echo(df.to_csv(index=False))
    else:
        typer.echo(df.to_string(index=False))


class _DemoSettings(BaseServiceSettings):
    """Settings for `astk demo` - deliberately defaults to a config that needs
    no real database or webhook, so the command works with nothing set up.
    """

    app_name: str = "astk-demo"
    database_url: str | None = "sqlite:///:memory:"
    slack_webhook_url: str | None = "https://hooks.slack.com/services/DEMO/NOT-REAL/0000000000"


@app.command()
def demo(
    json_path: str | None = typer.Option(
        None, "--json", help="Also write a machine-readable summary to this path."
    ),
) -> None:
    """Run every astk piece - settings, db, alerts, dedup, logging - end to end
    against an in-memory SQLite database. Needs no config, no secrets, no
    network: this is what to run first to see the library actually work.
    """
    settings = load_settings(_DemoSettings)
    run_id = configure_logging(settings.app_name)
    logging.getLogger("astk.demo").info("astk demo run started")

    engine = make_engine(settings.dsn())
    demo_rows = [
        {"id": 1, "name": "Argan Oil 100ml", "margin_pct": 42.5},
        {"id": 2, "name": "Rosehip Serum 30ml", "margin_pct": 38.1},
        {"id": 3, "name": "Gift Coffret Trio", "margin_pct": 55.0},
    ]
    with session_scope(engine) as session:
        # DROP first: make_engine caches one Engine per URL (shared StaticPool
        # for ":memory:"), so a second `demo` call in the same process - every
        # test run, for one - hits the same in-memory database as the first.
        session.execute(text("DROP TABLE IF EXISTS demo_products"))
        session.execute(
            text("CREATE TABLE demo_products (id INTEGER PRIMARY KEY, name TEXT, margin_pct REAL)")
        )
        insert_sql = text(
            "INSERT INTO demo_products (id, name, margin_pct) VALUES (:id, :name, :margin_pct)"
        )
        for row in demo_rows:
            session.execute(insert_sql, row)

    written = len(demo_rows)
    read_back = len(fetch_df(engine, "SELECT * FROM demo_products"))
    is_healthy = healthcheck(engine)

    dedup = Deduplicator(ttl_s=3600)
    first_send = dedup.should_send("demo:margin-alert")
    second_send = dedup.should_send("demo:margin-alert")

    lowest = min(demo_rows, key=lambda r: r["margin_pct"])
    alert_fields = {
        "lowest_margin_product": lowest["name"],
        "lowest_margin_pct": str(lowest["margin_pct"]),
    }
    result = ConsoleNotifier().send(
        Alert(
            title="Demo alert",
            body="astk demo wiring works end to end",
            severity="warning",
            fields=alert_fields,
        )
    )

    typer.echo("")
    typer.echo("SETTINGS")
    typer.echo(f"  {settings!r}")
    typer.echo("")
    typer.echo("DATABASE")
    typer.echo(f"  wrote {written} rows")
    typer.echo(f"  read {read_back} rows")
    typer.echo(f"  healthcheck: {'ok' if is_healthy else 'FAIL'}")
    typer.echo("")
    typer.echo("DEDUP")
    typer.echo(f"  should_send('demo:margin-alert') -> {first_send}   (first call, accepted)")
    typer.echo(f"  should_send('demo:margin-alert') -> {second_send}  (second call, same key)")
    typer.echo("")
    typer.echo("ALERT")
    typer.echo(f"  ok={result.ok} attempts={result.attempts} error={result.error}")
    typer.echo("")
    typer.echo(f"run_id={run_id}")

    if json_path:
        summary = {
            "settings": {
                "app_name": settings.app_name,
                "env": settings.env,
                "log_level": settings.log_level,
                "database_url": settings.dsn(),
                "slack_webhook_url": "***" if settings.slack_webhook_url else None,
            },
            "database": {"wrote": written, "read": read_back, "healthcheck": is_healthy},
            "dedup": {"first": first_send, "second": second_send},
            "alert": {"ok": result.ok, "attempts": result.attempts, "error": result.error},
            "run_id": run_id,
        }
        Path(json_path).write_text(json.dumps(summary, indent=2))
        typer.echo(f"\nwrote summary to {json_path}")

    raise typer.Exit(code=0 if is_healthy and result.ok else 1)


@app.command()
def version() -> None:
    """Print the installed astk version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
