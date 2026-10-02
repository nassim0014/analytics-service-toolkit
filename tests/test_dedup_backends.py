"""Tests for the pluggable `DedupBackend` protocol:
`InMemoryDedupBackend` (the existing behaviour,
extracted), `PostgresDedupBackend` (new - SQL-building path only, no real
Postgres required), and `create_dedup_table`.

The real-Postgres concurrency test (two workers racing on the same key must
produce exactly one winner) is `@pytest.mark.postgres`, skipped unless
`ASTK_TEST_POSTGRES_URL` is set - there is no Postgres instance in this
environment, so it has never actually run here. Everything else is verified
against fakes/sqlite and does run.
"""

from __future__ import annotations

import os
import time
from datetime import timedelta

import pytest

from astk.alerts import (
    Deduplicator,
    InMemoryDedupBackend,
    PostgresDedupBackend,
    create_dedup_table,
)

# --- InMemoryDedupBackend ---------------------------------------------------


def test_in_memory_backend_wins_the_first_claim():
    backend = InMemoryDedupBackend()
    assert backend.claim("k", timedelta(seconds=60)) is True


def test_in_memory_backend_refuses_a_second_claim_within_ttl():
    backend = InMemoryDedupBackend()
    assert backend.claim("k", timedelta(seconds=60)) is True
    assert backend.claim("k", timedelta(seconds=60)) is False


def test_in_memory_backend_allows_again_after_ttl_expires():
    backend = InMemoryDedupBackend()
    assert backend.claim("k", timedelta(seconds=0.02)) is True
    time.sleep(0.05)
    assert backend.claim("k", timedelta(seconds=0.02)) is True


def test_in_memory_backend_keys_are_independent():
    backend = InMemoryDedupBackend()
    assert backend.claim("a", timedelta(seconds=60)) is True
    assert backend.claim("b", timedelta(seconds=60)) is True


# --- Deduplicator delegates to a pluggable backend --------------------------


class _RecordingBackend:
    def __init__(self, wins: list[bool]):
        self._wins = list(wins)
        self.calls: list[tuple[str, timedelta]] = []

    def claim(self, key: str, ttl: timedelta) -> bool:
        self.calls.append((key, ttl))
        return self._wins.pop(0)


def test_deduplicator_delegates_to_injected_backend():
    backend = _RecordingBackend([True, False])
    dedup = Deduplicator(ttl_s=45, backend=backend)

    assert dedup.should_send("margin:kinz-oil") is True
    assert dedup.should_send("margin:kinz-oil") is False
    assert backend.calls == [
        ("margin:kinz-oil", timedelta(seconds=45)),
        ("margin:kinz-oil", timedelta(seconds=45)),
    ]


def test_deduplicator_defaults_to_in_memory_backend():
    dedup = Deduplicator(ttl_s=60)
    assert isinstance(dedup._backend, InMemoryDedupBackend)


# --- PostgresDedupBackend: SQL-building path, no live Postgres needed -------


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeConnection:
    def __init__(self, rows):
        self._rows = rows
        self.executed: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), dict(params or {})))
        return _FakeResult(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeEngine:
    def __init__(self, rows):
        self._conn = _FakeConnection(rows)

    def begin(self):
        return self._conn


def test_postgres_backend_claim_wins_when_a_row_comes_back():
    engine = _FakeEngine(rows=[("some-key",)])
    backend = PostgresDedupBackend(engine)

    assert backend.claim("some-key", timedelta(seconds=300)) is True


def test_postgres_backend_claim_loses_when_no_row_comes_back():
    engine = _FakeEngine(rows=[])
    backend = PostgresDedupBackend(engine)

    assert backend.claim("some-key", timedelta(seconds=300)) is False


def test_postgres_backend_claim_is_a_single_atomic_upsert_not_read_then_write():
    # Exactly one statement, an INSERT .. ON CONFLICT .. RETURNING - not a
    # SELECT followed by an INSERT/UPDATE, which would race between two
    # workers the way the `claim` contract exists to prevent.
    engine = _FakeEngine(rows=[("k",)])
    backend = PostgresDedupBackend(engine)
    backend.claim("k", timedelta(seconds=300))

    assert len(engine._conn.executed) == 1
    sql, params = engine._conn.executed[0]
    assert "INSERT INTO astk_alert_dedup" in sql
    assert "ON CONFLICT (key) DO UPDATE" in sql
    assert "RETURNING key" in sql
    assert "astk_alert_dedup.expires_at < now()" in sql
    assert params["key"] == "k"
    assert "expires_at" in params


def test_postgres_backend_uses_a_custom_table_name():
    engine = _FakeEngine(rows=[("k",)])
    backend = PostgresDedupBackend(engine, table_name="my_dedup_table")
    backend.claim("k", timedelta(seconds=300))

    sql, _ = engine._conn.executed[0]
    assert "INSERT INTO my_dedup_table" in sql
    assert "my_dedup_table.expires_at < now()" in sql


def test_postgres_backend_rejects_an_unsafe_table_name():
    with pytest.raises(ValueError, match="identifier"):
        PostgresDedupBackend(_FakeEngine(rows=[]), table_name="astk_alert_dedup; DROP TABLE x")


def test_create_dedup_table_rejects_an_unsafe_table_name():
    with pytest.raises(ValueError, match="identifier"):
        create_dedup_table(_FakeEngine(rows=[]), table_name="x; DROP TABLE y")


def test_create_dedup_table_issues_create_if_not_exists():
    engine = _FakeEngine(rows=[])
    create_dedup_table(engine)

    sql, _ = engine._conn.executed[0]
    assert "CREATE TABLE IF NOT EXISTS astk_alert_dedup" in sql
    assert "PRIMARY KEY" in sql


def test_create_dedup_table_honours_a_custom_table_name():
    engine = _FakeEngine(rows=[])
    create_dedup_table(engine, table_name="my_dedup_table")

    sql, _ = engine._conn.executed[0]
    assert "CREATE TABLE IF NOT EXISTS my_dedup_table" in sql


# --- Real Postgres concurrency test: skipped without a live database -------


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("ASTK_TEST_POSTGRES_URL"),
    reason="set ASTK_TEST_POSTGRES_URL to run the live-Postgres concurrency test",
)
def test_postgres_backend_two_racing_claims_produce_exactly_one_winner():
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import create_engine

    engine = create_engine(os.environ["ASTK_TEST_POSTGRES_URL"])
    create_dedup_table(engine, table_name="astk_test_dedup_race")
    backend = PostgresDedupBackend(engine, table_name="astk_test_dedup_race")
    key = f"race-{time.monotonic()}"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: backend.claim(key, timedelta(seconds=60)), range(2))
        )

    assert sorted(results) == [False, True]
