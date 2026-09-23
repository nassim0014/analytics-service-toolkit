# Changelog

All notable changes to `astk` (`analytics-service-toolkit`) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Pre-1.0: minor version bumps may break the API; patch bumps never do. See the
"Compatibility" section of `README.md`.

## [Unreleased]

### Added

- `CHANGELOG.md` (this file).
- `astk.__version__` now reads from installed package metadata
  (`importlib.metadata.version("analytics-service-toolkit")`) instead of a
  hardcoded string literal, so it can't drift from `pyproject.toml`.
- "Compatibility" section in `README.md` documenting the pre-1.0 versioning
  policy.

## [0.1.0] - 2026-08-27

Initial module set.

### Added

- `astk.settings` — `BaseServiceSettings` / `load_settings()`, pydantic-based
  configuration loading with SQLite and Postgres `database_url` support.
- `astk.db` — `make_engine()`, `session_scope()`, `fetch_df()`,
  `wait_for_db()`, `healthcheck()`. SQLite connections get
  `journal_mode=WAL` + `busy_timeout=30000` applied automatically
  (file-backed and `:memory:`).
- `astk.alerts` — `SlackNotifier`, `ConsoleNotifier`, `Alert`,
  `Deduplicator`. Notifiers never raise into the caller; failures come back
  as a failed `AlertResult`.
- `astk.dashboard` — Streamlit chrome (`page_header`, `kpi_row`,
  `timeseries`, `cached_query`). `cached_query(engine, sql, params=None)` is
  correctly keyed per-engine and supports parameterised queries (this shape
  landed after the initial cut — see "Fixed" below).
- `astk.logging` — `configure_logging()`.
- `astk` CLI (`astk doctor`, `astk alert`, `astk query`, `astk version`).

### Fixed

- `dashboard.cached_query()` silently served one engine's rows to a second
  engine because `engine` was captured outside the Streamlit cache key. Fixed
  by moving the query onto a module-level cached function keyed on
  `(str(engine.url), sql, sorted(params))`. **Breaking:** the third
  positional argument changed from `ttl_s: int` to `params: dict | None`
  (acceptable pre-1.0 — the repo had zero consumers of this function at the
  time).
- `settings.database_url` was `PostgresDsn`-only and rejected the
  `sqlite:///…` URLs every service actually uses in tests. Now a validated
  `str`.
- Slack severity colour didn't render (`blocks` were nested outside the
  coloured attachment).
- `db.healthcheck(timeout_s)` ignored its timeout; a hung connect blocked
  indefinitely. Now bounded on a worker thread.
- `SlackNotifier` slept needlessly after its final retry attempt; gained
  `close()` / context-manager support.
