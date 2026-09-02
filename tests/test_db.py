import pytest
from sqlalchemy import text

from astk.db import fetch_df, healthcheck, make_engine, session_scope, wait_for_db


@pytest.fixture
def sqlite_engine():
    make_engine.cache_clear()
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)"))
    yield engine
    make_engine.cache_clear()


def test_session_scope_commits_on_success(sqlite_engine):
    with session_scope(sqlite_engine) as session:
        session.execute(text("INSERT INTO items (id, name) VALUES (1, 'a')"))

    df = fetch_df(sqlite_engine, "SELECT * FROM items")
    assert len(df) == 1
    assert df.iloc[0]["name"] == "a"


def test_session_scope_rolls_back_on_exception(sqlite_engine):
    with pytest.raises(RuntimeError):
        with session_scope(sqlite_engine) as session:
            session.execute(text("INSERT INTO items (id, name) VALUES (2, 'b')"))
            raise RuntimeError("boom")

    df = fetch_df(sqlite_engine, "SELECT * FROM items")
    assert len(df) == 0


def test_fetch_df_returns_dataframe(sqlite_engine):
    df = fetch_df(sqlite_engine, "SELECT 1 AS one")
    assert df.iloc[0]["one"] == 1


def test_fetch_df_accepts_params(sqlite_engine):
    with session_scope(sqlite_engine) as session:
        session.execute(text("INSERT INTO items (id, name) VALUES (1, 'a'), (2, 'b')"))

    df = fetch_df(sqlite_engine, "SELECT * FROM items WHERE name = :name", {"name": "b"})
    assert len(df) == 1
    assert df.iloc[0]["id"] == 2


def test_healthcheck_true_for_working_engine(sqlite_engine):
    assert healthcheck(sqlite_engine) is True


def test_healthcheck_false_for_broken_engine():
    make_engine.cache_clear()
    engine = make_engine("sqlite:////nonexistent-directory/does-not-exist.db")
    assert healthcheck(engine) is False
    make_engine.cache_clear()


class _FlakyEngine:
    """Duck-typed stand-in for a SQLAlchemy Engine that fails to connect N times."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def connect(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("connection refused")
        return _FakeConnection()


class _FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, *args, **kwargs):
        return None


def test_wait_for_db_retries_then_succeeds():
    engine = _FlakyEngine(fail_times=2)
    assert wait_for_db(engine, timeout_s=5, interval_s=0.01) is True
    assert engine.calls == 3


def test_wait_for_db_times_out_and_returns_false():
    engine = _FlakyEngine(fail_times=1000)
    assert wait_for_db(engine, timeout_s=0.05, interval_s=0.01) is False
    assert engine.calls > 0


# --- audit-fix coverage: healthcheck honours its timeout --------------------

import time as _time  # noqa: E402


class _SlowEngine:
    """Engine whose connect() blocks — models a hung TCP connect to a dead DB."""

    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s

    def connect(self):
        _time.sleep(self.delay_s)
        return _FakeConnection()


def test_healthcheck_times_out_promptly_on_a_slow_engine():
    engine = _SlowEngine(delay_s=2.0)
    start = _time.monotonic()
    assert healthcheck(engine, timeout_s=0.1) is False
    # It must give up near the timeout, not wait the full 2s.
    assert _time.monotonic() - start < 1.0


def test_healthcheck_zero_timeout_runs_inline(sqlite_engine):
    assert healthcheck(sqlite_engine, timeout_s=0) is True
