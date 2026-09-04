# Adoption guide

What each KINZ service currently hand-rolls, and what it would delete by
depending on `astk` instead.

**Verified 2026-09-04 (closed loop, laptop) against the actual source of all
four repos** — the original version of this doc (2026-08-19) was written from
the outside, from each repo's README and file layout, and its per-repo claims
had never been checked against real code. That check is item 3 in
`docs/IMPROVEMENTS.md`. Every row below is either confirmed with a
`path/to/file.py:LINE` citation, corrected, or marked `UNVERIFIED`. Table/column
names and connection strings are deliberately kept generic per this repo's own
"no KINZ business logic or domain data" rule (see `CLAUDE.md`) — evidence here
is about code *shape*, not the underlying business data.

## kinz-margin-guardian-pipeline

**Correction: this is no longer a "before/after" pitch — three of the four
rows are already adopted.** The original doc assumed zero consumers; this repo
adopted `astk` for settings, DB and alerting at some point before this check
(no in-repo changelog entry ties it to a date). This is the toolkit's one real
production consumer today, ahead of item 1's plan to make `kinz-price-bridge`
the first one.

| Concern | Status | Evidence | Blocker |
|---|---|---|---|
| Settings | **Adopted** | `src/config.py:17` imports `astk.settings.{BaseServiceSettings, load_settings}`; `GuardianSettings(BaseServiceSettings)` at `src/config.py:22`, loaded via `load_settings(GuardianSettings)` at `src/config.py:53`. | — |
| DB | **Adopted** (API path only — see Dashboard row) | `api/database.py:12` imports `astk.db.make_engine`; `api/database.py:17` calls it directly for the FastAPI engine. | — |
| Alerting | **Adopted**, with a documented degrade path | `src/alert_manager.py:29` imports `astk.alerts.{Alert, SlackNotifier}` inside a `try/except ModuleNotFoundError`, because `astk` is private and the lightweight CI job that only exercises the pure `dag_logic.py` helpers doesn't install it. Delivery still degrades to log-only on any failure — the module docstring is explicit that this is deliberate. | — |
| Dashboard | **Not adopted** — original claim was aspirational | `dashboard/app.py:25` still calls bare `st.set_page_config(...)` directly, and `dashboard/app.py:41-42` (`get_engine()`) still calls raw SQLAlchemy `create_engine(DATABASE_URL)` instead of the already-imported `astk.db.make_engine` that `api/database.py` uses two files over. So the same service now has two different engine-construction code paths for the same database — a real, cheap-to-fix inconsistency worth filing back as its own item rather than assuming this row's "after" already shipped. | None technical — `astk.dashboard.health_gauge`/`timeseries`/`page_header` all exist (verified in `src/astk/dashboard.py`) and the API side already proves `make_engine` works against this service's DB. This is just undone work. |

## kinz-competitor-intelligence

**Correction: no `astk` import anywhere in this repo** (`grep -rln astk .` is
empty) — the original "After" column was never contradicted, but it also
wasn't checked against a real, concrete blocker that exists in this repo's DB
layer.

| Concern | Status | Evidence | Blocker |
|---|---|---|---|
| Settings | Not adopted | `src/config.py:6,19` — its own `dotenv.load_dotenv(ROOT / ".env", override=False)`, with a deliberate comment (`src/config.py:13-18`) explaining why real env vars must win over `.env`. Plain `os.getenv(...)` calls, no settings class. | Likely none — `pydantic-settings`' own default precedence (env > dotenv > default) already matches this repo's `override=False` intent, so a `BaseServiceSettings` subclass probably preserves it. Not fully proven; flag as low-risk rather than blocker-free. |
| DB | Not adopted | `src/database.py:17,59` calls `create_engine(...)` directly (two branches: SQLite and Postgres); `src/database.py:61` builds its own `sessionmaker`. | **Real, concrete blocker.** `src/database.py:45,48` sets `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=30000` on every pooled connection via a SQLAlchemy event listener — this is what lets the scraper write to `data/competitors.db` while the dashboard reads it concurrently without "database is locked" errors (see the surrounding comment block, `src/database.py:29-51`). `astk.db.make_engine` (`src/astk/db.py:23-52`) has no WAL/busy_timeout handling for file-backed SQLite — it only special-cases `:memory:` URLs with `StaticPool`. Swapping in `make_engine` today would silently drop WAL mode and reintroduce the locking failures this code was written to fix. This matches the standing note in the loop-engine registry not to migrate this repo's DB layer to `astk.db` for exactly this reason. |
| Dashboard | Not adopted | `dashboard/app.py:44` calls bare `st.set_page_config(...)`. | None found for the "chrome" parts (`page_header`, `kpi_row`) beyond the DB blocker above, since the dashboard reads through the same engine. `data_table(df, editable=True)` (the original claim) is plausible but not checked against a specific editable-table call site in this pass. |

Also present but not previously listed: `src/config.py:156` and
`src/scrapers/instagram_scraper.py:259` both call `logging.basicConfig(...)`
directly — `astk` has no `configure_logging()` helper of its own to point at
yet (only `BaseServiceSettings.log_level` as a field), so this isn't a gap in
this repo, it's a gap in `astk` if structured logging setup is ever meant to
be part of the pitch. Filed as a note, not a new backlog item — see
`docs/IMPROVEMENTS.md` if this becomes worth doing.

## kinz-secure-commerce-hub

Confirms the original doc's framing (mostly TypeScript/Next.js frontend, Python
FastAPI + ETL backend) but adds one concrete, previously-unlisted blocker.

| Concern | Status | Evidence | Blocker |
|---|---|---|---|
| Settings | Not adopted | `src/api/utils/config.py:12,27` — its own `pydantic_settings.BaseSettings` subclass (not `astk`'s). | **Real blocker, not previously listed.** `src/api/utils/config.py:16-24,119` defines a fail-fast check: if `JWT_SECRET` (or other fields) matches a known-insecure placeholder value, the app refuses to start when running in production. `astk.settings.BaseServiceSettings` (`src/astk/settings.py`) has no equivalent check for any of its fields. Adopting it as-is would silently drop a real security guard rather than just being a lateral move — this needs the check ported into `astk` (or kept as a subclass override) before adoption, not skipped. |
| DB | N/A | No SQLAlchemy `create_engine`/`sessionmaker` found outside `tests/backend/test_models.py` — this service's persistence path was not fully traced in this pass (async ORM usage was not confirmed or ruled out; `src/api/main.py` etc. have 5 `async def` routes/middlewares). | **Unverified**, not "no overlap" — the original doc undersold this by implying only "ETL side" has DB overlap. Needs a follow-up pass specifically tracing `src/pipeline/` for its actual DB access pattern before claiming an "After" state here. |
| Alerting / reconciliation job | UNVERIFIED — original claim was speculative | No `slack`/`webhook` hits anywhere in `src/` (`grep -rniE "slack|webhook" --include="*.py"` is empty), and no file matching `*reconcil*`/`*nightly*` exists. The "nightly reconciliation job" and "any operational alerting it grows" language in the pre-verification version of this doc described something that does not exist in the repo today. | Not a blocker — there's simply nothing to adopt `astk.alerts` into yet. Correct this claim to "no alerting exists yet; revisit if/when one is built," per `astk`'s own "add on demand" policy in `docs/IMPROVEMENTS.md`'s "Deliberately not on this list" section. |

`logging.basicConfig(...)` appears at `src/api/main.py:30`,
`src/pipeline/jobs/run_etl.py:118`, and `src/pipeline/jobs/scheduler.py:35` —
same non-gap as competitor-intelligence above.

## kinz-accounting-analysis-*

| Concern | Status | Evidence | Blocker |
|---|---|---|---|
| Settings | Not adopted | `scripts/config.py:31-33` and surrounding lines — plain `os.environ.get(...)` calls for Odoo/Shopify connection config, no settings class of any kind (not even a hand-rolled `pydantic.BaseSettings`, unlike the other three repos). | None technical for adding a `BaseServiceSettings` subclass. Worth noting this repo's secrets (API tokens) currently have **no default and no dedicated validation** beyond "the script raises later if unset" — adopting `BaseServiceSettings` would be a strict improvement here, not just a lateral move, unlike the other repos in this doc. |
| DB | **N/A — confirmed, not a gap** | No `create_engine`/`sessionmaker`/any SQL DB anywhere in the repo; it reads/writes CSVs and Parquet-style files under `data/processed`, `analysis/`, `audit/`, `compliance/` per `scripts/config.py:14-19`. The original doc correctly omitted a DB row for this repo. | N/A — `astk.db` has nothing to attach to here. |
| Dashboard | Not adopted | `dashboard/app.py:33` calls bare `st.set_page_config(...)`. | None found in this pass — the dashboard's own `dashboard/components.py` module (referenced at `dashboard/app.py:26`) was not traced for KPI/table code that would map onto `astk.dashboard.kpi_row`/`data_table`; do that before treating this row as blocker-free. |

## What adoption does *not* mean

Genesis-loop-created repos aside, this toolkit is never pushed into an
existing repo automatically. Adopting `astk` in any of the above (beyond what
`kinz-margin-guardian-pipeline` has already done on its own) is a separate,
deliberate change made in that repo, at a time of the owner's — or another
loop cycle's — choosing.
