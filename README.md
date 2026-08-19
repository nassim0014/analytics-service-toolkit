# analytics-service-toolkit (`astk`)

A small shared library that pulls the operational plumbing four independent
Python services in this portfolio were each reimplementing on their own:
`.env` settings loading, Postgres connection handling (including the "app
container started before Postgres was ready" race), Slack alerting with
retry/backoff, and Streamlit dashboard chrome (KPI rows, health gauges,
timeseries, editable tables).

It contains **no business logic and no domain data** — no KINZ schema, no
scrapers, no competitor names, no price normalization. It's infrastructure
only, which is what makes it safe to be public and safe to import from any
service regardless of what that service does.

## Why this exists

`kinz-competitor-intelligence`, `kinz-margin-guardian-pipeline`,
`kinz-secure-commerce-hub`, and `kinz-accounting-analysis` each independently
hand-roll: a pydantic settings class, a SQLAlchemy engine + session helper, a
Streamlit dashboard's KPI/gauge/table chrome, and (in margin-guardian's case)
Slack alerting. Four copies of the same substrate, no shared code, no shared
tests. This library is that shared layer, extracted once and tested once.

It is deliberately **not** `kinz-price-bridge` — that repo owns the domain
logic of turning scraped competitor listings into a normalized price feed.
This toolkit is what a project like that would be *built on*, not a
replacement for it.

## What's here (v1)

- **`astk.settings`** — `BaseServiceSettings` (a pydantic-settings base class
  with `app_name`, `env`, `log_level`, `database_url`, `slack_webhook_url`)
  and `load_settings()`, which turns a `pydantic.ValidationError` into a
  readable "missing: X, Y / invalid: Z" message instead of a raw traceback.
  Secrets are redacted in `repr()`.
- **`astk.db`** — `make_engine()` (cached per URL, SQLite-in-memory-safe),
  `session_scope()` (commit/rollback contextmanager), `fetch_df()` (SQL →
  pandas DataFrame), `healthcheck()`, and `wait_for_db()` (polls until the
  database is reachable — the fix for the Docker Compose startup race).
- **`astk.alerts`** — `Alert` / `AlertResult` value objects, `SlackNotifier`
  (retries on 429/5xx with exponential backoff, **never raises** — a broken
  alert channel must not take down the service using it), `ConsoleNotifier`
  for dev, and `Deduplicator` (suppress a repeated alert key within a TTL so
  a flapping threshold doesn't spam the channel once per DAG run).
- **`astk.dashboard`** — Streamlit chrome: `page_header`, `kpi_row`,
  `health_gauge`, `timeseries`, `data_table`, `sidebar_filters`,
  `cached_query`. The formatting/threshold logic (`format_value`,
  `threshold_color`) is factored into plain functions so it's unit-testable
  without a Streamlit runtime. Streamlit is an optional dependency.
- **`astk.logging`** — `configure_logging()`: one call, JSON log lines
  tagged with the service name and a per-run id.
- **`astk` CLI** (Typer) — `astk doctor` checks DB connectivity and Slack
  webhook reachability in one shot; `astk alert`, `astk query`, `astk
  version`.

## Install

```bash
pip install "analytics-service-toolkit[streamlit] @ git+https://github.com/nassim0014/analytics-service-toolkit"
```

Extras: `[streamlit]` for the dashboard helpers, `[postgres]` for the
`psycopg2` driver, `[dev]` for the test/lint toolchain.

## Quick start

```python
from astk.settings import BaseServiceSettings, load_settings
from astk.db import make_engine, wait_for_db, fetch_df
from astk.alerts import Alert, SlackNotifier, Deduplicator

class MySettings(BaseServiceSettings):
    app_name: str = "my-service"

settings = load_settings(MySettings)
engine = make_engine(str(settings.database_url))
wait_for_db(engine, timeout_s=30)

df = fetch_df(engine, "SELECT * FROM products LIMIT 10")

notifier = SlackNotifier(str(settings.slack_webhook_url))
dedup = Deduplicator(ttl_s=3600)
if dedup.should_send("margin:low"):
    notifier.send(Alert(title="Margin alert", body="B2C margin below 10%", severity="critical"))
```

```bash
astk doctor --database-url postgresql://... --slack-webhook-url https://hooks.slack.com/...
streamlit run examples/demo_app.py   # a working end-to-end demo against fake, seeded data
```

## What's not built yet

Being honest about v1's edges — see [docs/IMPROVEMENTS.md](docs/IMPROVEMENTS.md)
for the full ranked list:

- `Deduplicator` is in-memory/per-process only. A Postgres-backed variant
  for multi-process dedup (e.g. several Airflow workers) doesn't exist yet.
- No async support (`asyncpg`/`AsyncSession`) — every KINZ service so far is
  synchronous, so this wasn't built speculatively.
- No email/PagerDuty notifier, only Slack + console.
- `astk doctor` checks reachability, not schema/migration state.
- No `pip`-installable release on PyPI — install straight from git for now.

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest --cov=astk --cov-report=term-missing
```

## License

MIT — see [LICENSE](LICENSE).
