"""Alerting: a small `Alert` value object, a Slack notifier with retry +
backoff that never raises into the caller, a console notifier for dev/tests,
and an in-memory deduplicator so a flapping threshold doesn't spam the
channel once per DAG run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx

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


class Deduplicator:
    """Suppresses repeat alerts sharing a key within a TTL window.

    In-memory only, per-process. Good enough for a single Airflow worker or
    a single long-running service; a Postgres-backed variant for
    multi-process dedup is not built yet (see docs/IMPROVEMENTS.md).
    """

    def __init__(self, ttl_s: float = 300.0) -> None:
        self.ttl_s = ttl_s
        self._seen: dict[str, float] = {}

    def should_send(self, key: str) -> bool:
        now = time.monotonic()
        last = self._seen.get(key)
        if last is not None and (now - last) < self.ttl_s:
            return False
        self._seen[key] = now
        return True
