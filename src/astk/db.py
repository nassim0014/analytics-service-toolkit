"""Database helpers shared by every service: engine creation, session scope,
DataFrame queries, and the Docker Compose startup race every one of these
services hits (app container starts before Postgres is ready to accept
connections).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from contextlib import contextmanager
from functools import cache
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@cache
def make_engine(
    url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_pre_ping: bool = True,
) -> Engine:
    """Create (and cache) a SQLAlchemy engine.

    Cached via ``functools.cache`` on the full argument tuple (``url`` plus the
    keyword pool options), so the common ``make_engine(url)`` call returns one
    shared engine per URL, while a call with different pool settings gets its
    own. The cache is process-lifetime — fine for a long-running service.

    SQLite in-memory URLs get `StaticPool` + `check_same_thread=False` so the
    same in-memory database survives across connections — plain SQLite
    otherwise hands every new connection a *fresh, empty* database, which is
    surprising the first time you hit it in tests.
    """
    kwargs: dict[str, Any] = {"pool_pre_ping": pool_pre_ping}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url == "sqlite://":
            kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_size"] = pool_size
        kwargs["max_overflow"] = max_overflow
    return create_engine(url, **kwargs)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Yield a session that commits on success and rolls back on exception."""
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def fetch_df(engine: Engine, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    """Run a read query and return the result as a DataFrame."""
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def healthcheck(engine: Any, timeout_s: float = 5.0) -> bool:
    """Return True if a trivial query succeeds against the engine within ``timeout_s``.

    The check runs on a worker thread and is abandoned if it takes longer than
    ``timeout_s`` seconds — so a hung TCP connect to an unreachable database
    returns ``False`` promptly instead of blocking the caller (which is the
    whole point of using this in ``wait_for_db`` at startup). ``timeout_s <= 0``
    disables the bound and runs inline.

    Accepts anything with an `engine.connect()` context manager whose
    connection has `.execute()` — real SQLAlchemy engines and test doubles
    both work, which is what lets `wait_for_db` be tested without a real
    database.
    """
    def _probe() -> bool:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True

    if timeout_s <= 0:
        try:
            return _probe()
        except Exception:
            return False

    # Run on a worker and bound the wait. shutdown(wait=False) is deliberate: a
    # `with` block (or wait=True) would join the worker on exit and re-block for
    # the full hung-connect duration, defeating the timeout. The abandoned
    # worker unwinds on its own once the underlying connect errors out.
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(_probe).result(timeout=timeout_s)
    except FuturesTimeout:
        return False
    except Exception:
        return False
    finally:
        pool.shutdown(wait=False)


def wait_for_db(engine: Any, timeout_s: float = 30.0, interval_s: float = 1.0) -> bool:
    """Poll `healthcheck` until it succeeds or `timeout_s` elapses.

    Use this at service startup instead of a fixed `sleep(10)` before the
    app tries to talk to Postgres.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        if healthcheck(engine):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval_s)
