# Improvements

Ranked backlog for `analytics-service-toolkit` (`astk`) after v1 scaffolding. Items are ordered by how much they increase the odds this library actually gets adopted by the KINZ services and stays correct — not by effort. Work top-down; each item is self-contained and has explicit acceptance criteria.

Current state at time of writing: 36 passed / 1 skipped, 89% coverage, ruff-clean, CI green, install-from-git only, zero real consumers.

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

## 2. Verify and fix `dashboard.cached_query()` — suspected broken caching

**What to do.** `cached_query()` currently defines a nested function inside the call and wraps it in `st.cache_data` on every invocation. `st.cache_data` keys its cache on the wrapped function's identity/qualified name plus its bytecode hash, so a freshly created closure per call is very likely to produce a cache that never hits across Streamlit reruns — meaning every rerun re-executes the SQL while still paying the hashing overhead.

1. Write a failing-first test: monkeypatch `fetch_df` with a call counter, invoke `cached_query()` twice with identical SQL and params (simulating two reruns), and assert the counter is `1`. Use `streamlit.testing.v1.AppTest` for a rerun-realistic path if the unit-level harness is not convincing.
2. If it hits once, the concern is disproven — leave the code alone and record the test plus a comment explaining why the pattern is safe, so this doesn't get re-litigated.
3. If it hits twice (expected), refactor to a single module-level function decorated once with `@st.cache_data`, taking only hashable arguments — `(url: str, sql: str, params: tuple)`. Any unhashable argument (engine, connection, session) must either be reconstructed inside from the URL via the already-cached `make_engine()`, or be passed with a leading-underscore parameter name so Streamlit excludes it from the hash key. Expose `ttl` and `show_spinner` as pass-throughs.

**Why second.** This is a plausible latent correctness/performance bug in the one module whose entire purpose is to make dashboards fast, and it is silent: nothing fails, the dashboard just quietly hammers the database on every widget interaction. It will be discovered by a consumer under load, at which point it looks like the shared library made things worse than the hand-rolled code it replaced — the single worst outcome for adoption. It is also cheap to settle definitively, and settling it either way (fix or documented test) is progress.

---

## 3. Verify `docs/ADOPTION.md` against the actual source of the four KINZ repos

**What to do.** `docs/ADOPTION.md` was written from the outside, by reading each repo's README and file listing — its per-repo "what this repo currently hand-rolls" claims were never checked against real code. For each of `kinz-competitor-intelligence`, `kinz-margin-guardian-pipeline`, `kinz-secure-commerce-hub`, `kinz-accounting-analysis`:

- Grep the actual source for the plumbing patterns `astk` claims to replace: `create_engine(`, `sessionmaker`, `hooks.slack.com`, `requests.post(.*webhook`, `logging.basicConfig`, `st.set_page_config`, `BaseSettings`, `os.environ[`.
- Rewrite each row with concrete `path/to/file.py:LINE` evidence and the approximate line count that `astk` would delete.
- Delete or explicitly mark `UNVERIFIED` any claim that doesn't survive contact with the source.
- Add a short "blockers" column: what in that repo would *prevent* adoption today (async usage, a Postgres-shared dedup requirement, a notifier `astk` doesn't have).

**Why third.** This doc is the pitch deck for the library — it's what a reader consults to decide whether adopting `astk` is worth it. If its specifics are wrong, the first engineer to check loses trust in the whole repo, and the incorrect claims will have been silently propagated into commit messages and READMEs by then. It also directly feeds the roadmap: the blockers column is the evidence base for ranking items 5 and 6 correctly, replacing guesswork with observation.

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

## Deliberately not on this list

Recorded so this doesn't get re-opened as "missing features" on a later pass. Each is a real gap; none is worth building on spec.

- **Async support (asyncpg / `AsyncSession`).** Every KINZ service today is synchronous. Building a parallel async API doubles the surface area and the test matrix to serve zero current consumers. Revisit when a repo is actually async — item 3's blockers column will surface it.
- **Email / PagerDuty notifiers.** The `Notifier` shape is already established by `SlackNotifier` and `ConsoleNotifier`, so adding one later is a contained change. Add on demand, not in anticipation; a notifier nobody has configured is a notifier nobody has tested against a live endpoint.
- **PyPI release.** The repo is private and all consumers are in the same GitHub org, where pinned git installs (item 4) work fine and leak nothing. Publishing adds a name to squat, a release workflow to maintain, and a public artifact — for no benefit until there's an external consumer.
