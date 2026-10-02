"""Alerting: a small `Alert` value object, a Slack notifier with retry +
backoff that never raises into the caller, a console notifier for dev/tests,
and an in-memory deduplicator so a flapping threshold doesn't spam the
channel once per DAG run.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Engine

Severity = Literal["info", "warning", "critical"]

_SEVERITY_COLOR = {
    "info": "#2563eb",
    "warning": "#d97706",
    "critical": "#dc2626",
}


@dataclass
class Alert:
    title: str
    body: str
    severity: Severity = "info"
    fields: dict[str, str] = field(default_factory=dict)
    link: str | None = None


@dataclass
class AlertResult:
    ok: bool
    attempts: int
    error: str | None = None


class Notifier(Protocol):
    def send(self, alert: Alert) -> AlertResult: ...


class ConsoleNotifier:
    """Prints the alert. Used in dev and as the CLI's default when no webhook is configured."""

    def send(self, alert: Alert) -> AlertResult:
        print(f"[{alert.severity.upper()}] {alert.title}: {alert.body}")
        for key, value in alert.fields.items():
            print(f"    {key}: {value}")
        return AlertResult(ok=True, attempts=1)


def _build_payload(alert: Alert) -> dict:
    color = _SEVERITY_COLOR.get(alert.severity, "#6b7280")
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": alert.title[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": alert.body}},
    ]
    if alert.fields:
        fields_text = "\n".join(f"*{k}:* {v}" for k, v in alert.fields.items())
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": fields_text}})
    if alert.link:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open"},
                        "url": alert.link,
                    }
                ],
            }
        )
    # Nest the blocks INSIDE the attachment so Slack renders the coloured
    # severity bar. A top-level `blocks` list with a separate `{"color": …}`
    # attachment (the previous shape) drew no colour at all — Slack only tints
    # content that lives inside the attachment.
    return {"attachments": [{"color": color, "blocks": blocks}]}


class SlackNotifier:
    """Posts to a Slack incoming webhook. Retries on 429/5xx with exponential
    backoff; on any other failure (bad webhook, network down, retries
    exhausted) it returns a failed `AlertResult` instead of raising — a
    broken alert channel must never take down the service that's trying to
    warn about something else.
    """

    def __init__(
        self,
        webhook_url: str,
        *,
        dry_run: bool = False,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        client: httpx.Client | None = None,
    ) -> None:
        if not isinstance(webhook_url, str) or not webhook_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError(
                "SlackNotifier webhook_url must be an http:// or https:// URL, got "
                f"{webhook_url!r}. A common cause is passing str(settings.slack_webhook_url) "
                "on a pydantic SecretStr (which yields '**********'); use "
                "settings.slack_webhook() instead."
            )
        self.webhook_url = webhook_url
        self.dry_run = dry_run
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        # Only close a client we created; a caller-supplied client stays the
        # caller's to manage.
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=10)

    def close(self) -> None:
        """Close the underlying httpx client if this notifier created it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> SlackNotifier:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def send(self, alert: Alert) -> AlertResult:
        if self.dry_run:
            return AlertResult(ok=True, attempts=0)

        payload = _build_payload(alert)
        last_error: str | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._client.post(self.webhook_url, json=payload)
            except httpx.HTTPError as exc:
                last_error = str(exc)
                self._sleep_if_retrying(attempt)
                continue

            if response.status_code < 300:
                return AlertResult(ok=True, attempts=attempt)
            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                self._sleep_if_retrying(attempt)
                continue
            # Non-retryable (4xx other than 429): stop immediately.
            return AlertResult(ok=False, attempts=attempt, error=f"HTTP {response.status_code}")

        return AlertResult(ok=False, attempts=self.max_retries, error=last_error)

    def _sleep_if_retrying(self, attempt: int) -> None:
        # No point sleeping after the final attempt — there is no retry after it.
        if attempt >= self.max_retries:
            return
        if self.backoff_base:
            time.sleep(self.backoff_base * (2 ** (attempt - 1)))


class DedupBackend(Protocol):
    """A pluggable suppression store for `Deduplicator`.

    `claim` must be a single atomic operation: if two callers race on the
    same key, exactly one may return `True`. This is what makes a backend
    safe to share across processes (N Airflow workers, N Gunicorn workers) —
    a read-then-write implementation would let both callers see "not claimed
    yet" and both send. `InMemoryDedupBackend` and `PostgresDedupBackend` are
    the two implementations here; `Deduplicator` itself only knows the
    protocol.
    """

    def claim(self, key: str, ttl: timedelta) -> bool:
        """Return True if the caller won `key` (and should send) and has
        claimed it for `ttl`; False if another caller already holds an
        unexpired claim on it.
        """
        ...


class InMemoryDedupBackend:
    """Per-process suppression state — the only backend that existed before
    `DedupBackend` was extracted. Good enough for a single long-running
    service or a single Airflow worker; N workers each get independent
    state, which is exactly the gap `PostgresDedupBackend` closes (see
    docs/IMPROVEMENTS.md item 5).
    """

    def __init__(self) -> None:
        self._expires_at: dict[str, float] = {}

    def claim(self, key: str, ttl: timedelta) -> bool:
        now = time.monotonic()
        expires_at = self._expires_at.get(key)
        if expires_at is not None and now < expires_at:
            return False
        self._expires_at[key] = now + ttl.total_seconds()
        return True


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(name: str) -> None:
    # The table name is interpolated directly into DDL/DML text below because
    # SQL doesn't support bind parameters for identifiers. It usually comes
    # from a hardcoded default or a service's own config, never end-user
    # input — but validating it here instead of trusting that is one line and
    # turns a possible injection into a clear `ValueError` at construction.
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(
            f"{name!r} is not a safe SQL identifier for a dedup table name "
            f"(must match {_IDENTIFIER_RE.pattern})"
        )


_CREATE_DEDUP_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS {table} (
    key TEXT PRIMARY KEY,
    expires_at TIMESTAMPTZ NOT NULL
)"""


def create_dedup_table(engine: Engine, table_name: str = "astk_alert_dedup") -> None:
    """Idempotently create the table `PostgresDedupBackend` claims against.

    Call this once at service startup, or skip it and paste the equivalent
    DDL into your own migrations instead:

        CREATE TABLE IF NOT EXISTS astk_alert_dedup (
            key TEXT PRIMARY KEY,
            expires_at TIMESTAMPTZ NOT NULL
        )
    """
    _validate_identifier(table_name)
    with engine.begin() as conn:
        conn.execute(text(_CREATE_DEDUP_TABLE_SQL.format(table=table_name)))


class PostgresDedupBackend:
    """Multi-process/multi-worker `DedupBackend`, backed by one table.

    `claim` is a single atomic upsert, not read-then-write:

        INSERT INTO <table> (key, expires_at) VALUES (:key, :expires_at)
        ON CONFLICT (key) DO UPDATE SET expires_at = :expires_at
            WHERE <table>.expires_at < now()
        RETURNING key

    A row comes back (claim won) only if the key was unclaimed or its
    previous claim already expired; two workers racing on the same key
    against the same database produce exactly one `True`. Requires
    `create_dedup_table(engine)` (or the equivalent DDL in your own
    migrations) to have run first. Postgres-specific (`ON CONFLICT`,
    `now()`, `RETURNING`) — this is not a generic-SQL backend.
    """

    def __init__(self, engine: Engine, table_name: str = "astk_alert_dedup") -> None:
        _validate_identifier(table_name)
        self._engine = engine
        self._table = table_name
        self._claim_sql = text(
            f"INSERT INTO {table_name} (key, expires_at) VALUES (:key, :expires_at) "
            f"ON CONFLICT (key) DO UPDATE SET expires_at = :expires_at "
            f"WHERE {table_name}.expires_at < now() "
            f"RETURNING key"
        )

    def claim(self, key: str, ttl: timedelta) -> bool:
        expires_at = datetime.now(UTC) + ttl
        with self._engine.begin() as conn:
            result = conn.execute(self._claim_sql, {"key": key, "expires_at": expires_at})
            return result.first() is not None


class Deduplicator:
    """Suppresses repeat alerts sharing a key within a TTL window.

    Backed by `InMemoryDedupBackend` by default (per-process only — see its
    docstring). Pass `backend=PostgresDedupBackend(engine)` for suppression
    state shared across multiple processes/workers.
    """

    def __init__(self, ttl_s: float = 300.0, *, backend: DedupBackend | None = None) -> None:
        self.ttl_s = ttl_s
        self._backend = backend if backend is not None else InMemoryDedupBackend()

    def should_send(self, key: str) -> bool:
        return self._backend.claim(key, timedelta(seconds=self.ttl_s))
