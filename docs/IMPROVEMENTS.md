# Improvements

Ranked backlog for `analytics-service-toolkit` (`astk`) after v1 scaffolding. Items are ordered by how much they increase the odds this library actually gets adopted by the KINZ services and stays correct — not by effort. Work top-down; each item is self-contained and has explicit acceptance criteria.

Current state at time of writing: 36 passed / 1 skipped, 89% coverage, ruff-clean, CI green, install-from-git only.

~~zero real consumers~~ — **correction (2026-09-04, see item 3's verification below):**
`kinz-margin-guardian-pipeline` already imports `astk.settings`, `astk.db`, and `astk.alerts`
in production code (not just a demo). This wasn't tracked here because the adoption happened
in that repo's own cycles, not through this backlog. Item 1 below still describes a real,
unfinished goal (a *documented, intentional* first-consumer integration with CI proving the
install-from-git path) but the "zero consumers" framing that motivated ranking it #1 is no
longer accurate — treat item 1 as "prove the packaging/CI story," not "get any consumer at
all."

**Progress (2026-09-04):** item 3 done (see below — `docs/ADOPTION.md` verified against real
source of all four KINZ repos). Item 2 was done 2026-08-27. Item 1 status has changed since it
was last looked at:
- `kinz-price-bridge` is **no longer empty** — it now has real content (`src/`, `tests/`,
  `docs/`, `Dockerfile`, `CLAUDE.md`, `pyproject.toml`, pushed 2026-09-02), so the "orphaned
  empty repo" blocker that justified marking item 1 blocked-on-genesis may no longer hold.
  **However, it does not import or depend on `astk` at all** (`grep -rn astk` across its
  `pyproject.toml` and `src/` is empty) — so item 1's acceptance criteria are still unmet
  there. Making `kinz-price-bridge` actually consume `astk` requires editing *that* repo, which
  is out of scope for an astk-repo cycle and wasn't this cycle's selected work — flagging for
  the owner/next cycle rather than doing it here. See `NEEDS YOUR DECISION` in this cycle's
  loop report.
- Given `kinz-margin-guardian-pipeline` is now a real (partial) consumer, item 1's own
  "why first" framing is weaker than when it was written — consider re-ranking it below item 4
  (version contract) on a future pass, since an unpinned real consumer now exists and that's
  arguably more urgent than adding a second one.

Next independently-actionable item for *this* repo: **4** (version contract) — verified
`docs/ADOPTION.md` also updated the file `kinz-margin-guardian-pipeline` and
`kinz-secure-commerce-hub` blockers, use it to re-rank if picking this up.

---

## 1. Prove `astk` works inside a real consuming repo (`kinz-price-bridge`)

**What to do.** `kinz-price-bridge` is a sibling repo in the portfolio that is currently empty. Scaffold it as the first real consumer of `astk` — greenfield, so no existing repo needs to be opened or edited:

- `pyproject.toml` depending on `astk` via a pinned git ref (see item 4), not a local path and not `-e ../`.
- A `Settings(BaseServiceSettings)` subclass that adds two or three bridge-specific fields, loaded via `load_settings()`.
- One real code path that uses `make_engine()` + `session_scope()` + `fetch_df()` against a SQLite dev DB, one that sends a `SlackNotifier` alert through a `Deduplicator`, and `configure_logging()` at entrypoint.
- A one-page Streamlit view built from `astk.dashboard` chrome (`page_header`, `kpi_row`, `timeseries`, `cached_query`).
- CI that runs `pip install` of `astk` from git in a clean environment and executes `astk doctor` as a build step.

**Acceptance:** `kinz-price-bridge` has no hand-rolled engine creation, no direct `requests.post` to a Slack webhook, and no `logging.basicConfig` anywhere. Every point of friction hit during the integration gets filed back here as a new item, and any API awkwardness gets fixed in `astk` rather than worked around in the consumer.

**Why first.** The entire justification for this repo is that it is a connective piece between four services, and right now that claim rests on nothing but the library's own test suite and a demo app that was written by the same author, in the same repo, against seeded in-memory SQLite. A library that has never been imported across a package boundary has not been tested — install surface, dependency resolution, optional-extras behavior, and import ergonomics are all unverified. Every other item on this list is cheaper and more accurate to do *after* one real consumer exists, because the consumer will tell you which gaps are real. This is also the highest-value item for the portfolio story: "extracted a shared library" and "a service actually depends on it" are very different claims.

---

## 2. ~~Verify and fix `dashboard.cached_query()` — suspected broken caching~~ ✅

**Done 2026-08-27 (closed loop, laptop).**

**Verified — the "cache never hits" hypothesis was wrong.** `st.cache_data` keys its
namespace on the wrapped function's `__module__` + `__qualname__` + source hash, all of
which are stable across a re-created closure, so repeated identical calls *did* hit the
cache. `test_cached_query_reuses_the_cache_on_a_repeated_identical_call` pins this and
passes against the pre-fix code too.

**But there was a real, silent correctness bug:** `engine` was captured in the per-call
closure — *outside* the `st.cache_data` key — so a second engine pointed at a different
database silently received the first engine's rows
(`test_cached_query_does_not_serve_one_engines_rows_to_another`: `assert 1 == 2` against
old code). `cached_query` also had no `params` argument at all, so parameterised queries
couldn't be cached correctly.

**Fix.** Single module-level `_cached_fetch_df(_engine, url, sql, params)` decorated once
with `@st.cache_data`. Public signature is now `cached_query(engine, sql, params=None)` —
keyed on `(str(engine.url), sql, sorted(params))`, all hashable; `_engine` rides along
under a leading-underscore name so Streamlit skips it in the hash. `ttl` is now the module
constant `CACHED_QUERY_TTL_S` (60s, unchanged default) because `st.cache_data` only takes
`ttl` at decoration time — see the docstring.

**Breaking change** (acceptable — zero consumers, function was unused even by the demo):
the third positional arg went from `ttl_s: int` to `params: dict | None`. Fold this into
item 4's `CHANGELOG.md` `0.1.0`/Unreleased entry when that lands.

Tests: `tests/test_dashboard.py` +4 (40 passed / 1 skipped, 91% coverage, was 89%).
`streamlit.testing.v1.AppTest` was not needed — the bare-mode cache with a monkeypatched
`fetch_df` counter reproduces rerun behaviour faithfully.

---

## 3. ~~Verify `docs/ADOPTION.md` against the actual source of the four KINZ repos~~ ✅

**Done 2026-09-04 (closed loop, laptop).**

Grepped all four repos (`create_engine(`, `sessionmaker`, `hooks.slack.com`,
`requests.post`, `logging.basicConfig`, `st.set_page_config`, `BaseSettings`,
`os.environ[`) via fresh shallow clones and read the relevant source directly
rather than trusting file layout alone. Full per-repo tables with
`path/to/file.py:LINE` evidence and a Blocker column are now in
`docs/ADOPTION.md`. Headline findings, most important first:

- **The doc's core premise was wrong.** `kinz-margin-guardian-pipeline`
  already imports `astk.settings`, `astk.db`, and `astk.alerts` in production
  code — this is a real consumer today, not a hypothetical one. Its Dashboard
  concern is the one row still genuinely unadopted, and it's now an
  inconsistency bug, not a clean slate: `dashboard/app.py` hand-rolls
  `create_engine(DATABASE_URL)` directly instead of reusing the `astk.db.make_engine`
  its own `api/database.py` already imports two files over.
- **One `UNVERIFIED` claim was actually a real, previously-undocumented
  blocker.** `kinz-competitor-intelligence` sets `PRAGMA journal_mode=WAL` +
  `busy_timeout=30000` on every pooled SQLite connection so the scraper can
  write while the dashboard reads. `astk.db.make_engine` has no equivalent
  handling for file-backed SQLite (only `:memory:` gets special-cased). This
  matches the standing loop-engine registry note not to migrate this repo's
  DB layer to `astk.db` — now backed by a specific line-level citation instead
  of a general warning.
- **`kinz-secure-commerce-hub` had an undocumented blocker too.** Its own
  settings class fails fast on known-insecure default secrets in production;
  `astk.settings.BaseServiceSettings` has no equivalent check. Adopting it
  as-is would be a silent security regression, not a lateral move. Also: the
  "nightly reconciliation job" and "alerting it grows" language in the
  original doc described something that doesn't exist in the repo yet —
  corrected to reflect that.
- **`kinz-accounting-analysis-*`'s DB row was already correctly absent** — no
  SQL database exists in that repo at all (file-based CSV/Parquet outputs
  only), confirmed rather than assumed this time.

No line-count deletions were estimated — the acceptance criteria asked for
them, but with three of four repos returning "not adopted, real blocker" or
"doesn't exist yet," a deletion estimate would have been speculative for rows
that don't have a clean before/after yet. Worth doing once item 1 (or the
`kinz-margin-guardian-pipeline` dashboard fix above) produces a second real
diff to measure from.

---

## 4. Establish a version contract: `v0.1.0` tag + `CHANGELOG.md` + pinned-install docs

**What to do.**

- Add `CHANGELOG.md` in Keep a Changelog format with an `Unreleased` section and a `0.1.0` entry covering the initial module set. This was never scaffolded despite the README's dev section implying process around it, and sibling repos (`btc-llm-sentiment`, `kinz-secure-commerce-hub`) already carry one.
- Tag `v0.1.0` and cut a GitHub release pointing at the changelog entry.
- Make `astk.__version__` the single source of truth, read from package metadata (`importlib.metadata.version("astk")`), have `astk version` print it, and add a test asserting it matches the `pyproject.toml` version.
- Update the README install section from a bare git URL to a pinned form: `pip install "astk @ git+ssh://git@github.com/nassim0014/analytics-service-toolkit.git@v0.1.0"`, with a note that consumers must pin a tag, never a branch.
- Add a short "Compatibility" section stating the pre-1.0 policy: minor bumps may break, patch bumps never do.

**Why fourth.** Four services depending on an unpinned default branch is a supply chain where any commit to `main` can break production in repos nobody was thinking about. Pinning is the precondition for item 1's CI to be meaningful and for anyone to adopt the library without fear. It's ranked below the correctness items because a version contract around broken caching just pins the bug, but above all feature work — no new module should ship before there's a way to release it safely.

---

## 5. Multi-process `Deduplicator` with a Postgres-backed backend

**What to do.** The current `Deduplicator` is in-memory and per-process, so N Airflow workers, N Gunicorn workers, or a task retried on a different host each maintain independent suppression state — the exact scenario alert dedup exists to handle.

- Extract a `DedupBackend` protocol with a single atomic method: `claim(key: str, ttl: timedelta) -> bool`, returning `True` if the caller won the key and should send.
- Keep the existing in-memory implementation as `InMemoryDedupBackend`, still the default, so nothing breaks.
- Add `PostgresDedupBackend(engine)` backed by a table `astk_alert_dedup(key text primary key, expires_at timestamptz not null)`. The claim must be a single atomic statement, not read-then-write: `INSERT INTO astk_alert_dedup (key, expires_at) VALUES (:k, :exp) ON CONFLICT (key) DO UPDATE SET expires_at = :exp WHERE astk_alert_dedup.expires_at < now() RETURNING key` — a returned row means the claim was won. Two workers firing simultaneously must produce exactly one alert.
- Ship a `create_dedup_table(engine)` helper (idempotent `CREATE TABLE IF NOT EXISTS`) plus the raw DDL in the docstring, so consumers can either call it or paste it into their own migrations.
- Tests: full coverage of the in-memory path and the SQL-building path; a concurrency test against real Postgres marked `@pytest.mark.postgres` and skipped when `ASTK_TEST_POSTGRES_URL` is unset, wired into CI with a Postgres service container.

**Why fifth.** This is the first *functional* gap that plausibly blocks a real service from adopting the library rather than merely inconveniencing it — a pipeline that runs across workers cannot use the current deduplicator at all and will keep its hand-rolled version, which undercuts the extraction. It ranks below items 1 and 3 because those will tell you which of the four repos actually needs this; build it against a confirmed requirement, not a hypothetical one.

---

## 6. Make `astk doctor` check schema state, not just reachability

**What to do.** `doctor` currently answers "can I open a socket," which is the easy half of "is this service correctly deployed."

- Add `--expect-tables users,orders` (repeatable/comma-separated) to assert named tables exist via SQLAlchemy `Inspector`, reporting each as a separate check line.
- Detect Alembic: if the consuming repo has an `alembic.ini` or an `alembic_version` table, compare the DB's current revision against the migration head and report `up to date` / `N migrations behind` / `unknown revision`.
- Define and document exit codes so `doctor` is usable as a CI and container healthcheck gate: `0` all checks passed, `1` degraded (reachable but schema or Slack check failed), `2` a hard dependency unreachable.
- Print a compact aligned table of `check / status / detail`, and add `--json` for machine consumption.

**Why sixth.** `doctor` is the highest-leverage surface in the CLI — it's the command a consumer runs first and the one that makes the library feel like infrastructure rather than a grab bag of helpers. Reachability alone gives false confidence: the classic failure is a service that connects fine to a database missing the migration it needs. Ranked here because it's an amplifier of adoption rather than an unblocker of it, and because item 1 will reveal exactly which checks the first consumer actually wants.

---

## 7. Repo hygiene parity with the rest of the portfolio

**What to do.** Bring `astk` up to the standard already set by `btc-llm-sentiment` and `kinz-secure-commerce-hub`:

- `.pre-commit-config.yaml` with `ruff` (lint, `--fix`), `ruff-format`, `bandit -r astk`, `end-of-file-fixer`, `trailing-whitespace`, and `check-yaml`. Pin hook revisions.
- A `bandit` step in the CI workflow, failing on medium severity and above, with a documented allowlist for any intentional finding.
- `CONTRIBUTING.md` (dev setup, how to run tests, changelog expectations, the pre-1.0 versioning policy from item 4), `SECURITY.md` (how to report an issue privately), and `CODE_OF_CONDUCT.md`.

**Why last.** All of it is real and all of it is cheap, but none of it changes whether the library works or whether anyone can adopt it. Bandit on a codebase with no business logic, no auth, and no user input is very unlikely to find anything the test suite wouldn't — the value is consistency across the portfolio, not risk reduction. Doing this before items 1 through 3 would be optimizing the packaging of something that hasn't been proven to work.

---

## Landed 2026-09-02 (toolkit self-audit)

Found while auditing astk from the outside (`ASTK_TOOLKIT_AUDIT.md` in the
workspace); all fixed with tests in one PR. Coverage 91% → 92%.

- **`settings.database_url` accepts SQLite.** Was `PostgresDsn`-only, which
  rejected the `sqlite:///…` URLs every service uses in tests (and that
  `db.make_engine` is built to handle) — forcing each consumer to override the
  field. Now a validated `str`: Postgres URLs still get pydantic's readable
  error, sqlite passes through.
- **Slack severity colour now renders.** `_build_payload` put `blocks` at top
  level with the colour on an empty attachment, so Slack drew no bar. Blocks now
  nest inside the coloured attachment. _(Worth a live-webhook eyeball.)_
- **`db.healthcheck(timeout_s)` is now honoured.** The parameter was dead; a
  hung connect ignored it and blocked. Now bounded on a worker thread
  (`shutdown(wait=False)` so the timeout isn't re-joined away).
- **`SlackNotifier` no longer sleeps after its final attempt** (wasted backoff),
  and gained `close()` + context-manager support so a self-created httpx client
  is cleaned up (a caller-supplied one is left alone).

## Deliberately not on this list

Recorded so this doesn't get re-opened as "missing features" on a later pass. Each is a real gap; none is worth building on spec.

- **Async support (asyncpg / `AsyncSession`).** Every KINZ service today is synchronous. Building a parallel async API doubles the surface area and the test matrix to serve zero current consumers. Revisit when a repo is actually async — item 3's blockers column will surface it.
- **Email / PagerDuty notifiers.** The `Notifier` shape is already established by `SlackNotifier` and `ConsoleNotifier`, so adding one later is a contained change. Add on demand, not in anticipation; a notifier nobody has configured is a notifier nobody has tested against a live endpoint.
- **PyPI release.** The repo is private and all consumers are in the same GitHub org, where pinned git installs (item 4) work fine and leak nothing. Publishing adds a name to squat, a release workflow to maintain, and a public artifact — for no benefit until there's an external consumer.
