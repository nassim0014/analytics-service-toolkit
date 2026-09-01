"""`astk` command-line entry point.

The flagship command is `astk doctor`: point it at a service's env vars and
it tells you, in one shot, whether the database and Slack webhook it depends
on are actually reachable — instead of finding out when the Airflow DAG
fails at 3am.
"""

from __future__ import annotations

import typer

from . import __version__
from .alerts import Alert, ConsoleNotifier, SlackNotifier
from .db import fetch_df, healthcheck, make_engine

app = typer.Typer(help="astk — shared operational toolkit for this portfolio's Python services.")


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


@app.command()
def version() -> None:
    """Print the installed astk version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
