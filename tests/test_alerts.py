import time

import pytest

from astk.alerts import Alert, ConsoleNotifier, Deduplicator, SlackNotifier


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def post(self, url, json=None):
        self.calls.append((url, json))
        return _FakeResponse(self._responses.pop(0))


def test_console_notifier_never_fails(capsys):
    result = ConsoleNotifier().send(Alert(title="t", body="b"))
    assert result.ok is True
    assert result.attempts == 1
    assert "t" in capsys.readouterr().out


def test_slack_notifier_success_first_try():
    client = _FakeClient([200])
    notifier = SlackNotifier("https://hooks.slack.com/x", client=client, backoff_base=0)

    alert = Alert(title="Margin drop", body="B2C margin below 10%", severity="critical")
    result = notifier.send(alert)

    assert result.ok is True
    assert result.attempts == 1
    payload = client.calls[0][1]
    assert payload["blocks"]
    assert payload["attachments"][0]["color"] == "#dc2626"


def test_slack_notifier_retries_on_5xx_then_succeeds():
    client = _FakeClient([500, 200])
    notifier = SlackNotifier("https://hooks.slack.com/x", client=client, backoff_base=0)

    result = notifier.send(Alert(title="t", body="b"))

    assert result.ok is True
    assert result.attempts == 2
    assert len(client.calls) == 2


def test_slack_notifier_never_raises_on_permanent_failure():
    client = _FakeClient([500, 500, 500])
    notifier = SlackNotifier(
        "https://hooks.slack.com/x", client=client, backoff_base=0, max_retries=3
    )

    result = notifier.send(Alert(title="t", body="b"))

    assert result.ok is False
    assert result.attempts == 3
    assert result.error == "HTTP 500"


def test_slack_notifier_stops_immediately_on_non_retryable_error():
    client = _FakeClient([404])
    notifier = SlackNotifier(
        "https://hooks.slack.com/x", client=client, backoff_base=0, max_retries=3
    )

    result = notifier.send(Alert(title="t", body="b"))

    assert result.ok is False
    assert result.attempts == 1
    assert len(client.calls) == 1


def test_slack_notifier_dry_run_sends_nothing():
    client = _FakeClient([])
    notifier = SlackNotifier("https://hooks.slack.com/x", client=client, dry_run=True)

    result = notifier.send(Alert(title="t", body="b"))

    assert result.ok is True
    assert client.calls == []


def test_slack_notifier_rejects_the_masked_secret_string():
    """Regression proof for the silent-alert-loss trap.

    On the OLD code `SlackNotifier("**********")` constructs fine and only fails at
    send time — returning `AlertResult(ok=False)` and raising nothing, so a service
    wired per the old README loses every alert silently. The fix rejects the URL at
    construction, where the mistake is still visible.
    """
    with pytest.raises(ValueError, match="http"):
        SlackNotifier("**********")


def test_slack_notifier_rejects_a_non_url_string():
    with pytest.raises(ValueError):
        SlackNotifier("not-a-url")


def test_slack_notifier_accepts_a_real_https_url():
    # The happy path must be untouched.
    client = _FakeClient([200])
    result = SlackNotifier(
        "https://hooks.slack.com/x", client=client, backoff_base=0
    ).send(Alert(title="t", body="b"))
    assert result.ok is True


def test_deduplicator_suppresses_repeat_within_ttl():
    dedup = Deduplicator(ttl_s=60)
    assert dedup.should_send("margin:kinz-oil") is True
    assert dedup.should_send("margin:kinz-oil") is False


def test_deduplicator_allows_again_after_ttl_expires():
    dedup = Deduplicator(ttl_s=0.02)
    assert dedup.should_send("k") is True
    time.sleep(0.05)
    assert dedup.should_send("k") is True


def test_deduplicator_keys_are_independent():
    dedup = Deduplicator(ttl_s=60)
    assert dedup.should_send("a") is True
    assert dedup.should_send("b") is True
