# CLAUDE.md — analytics-service-toolkit

Project rules and conventions for any agent (or human) working in this repo.

## What this repo is

A shared library (`astk`) extracted from the operational plumbing common to
this portfolio's KINZ Python services (settings, DB, alerting, dashboard
chrome). See [README.md](README.md) for the full pitch.

## The one rule that matters most

**No business logic. No domain data. Ever.**

This library must stay importable and safe to make public regardless of what
depends on it. That means:

- No KINZ table/column names, no competitor names, no real webhook URLs or
  connection strings — in code, tests, *or* docs. Use fictional names
  (`demo_margin_history`, `hooks.slack.com/x`, `postgresql://user:***@host`)
  everywhere, including in the demo app.
- No copying rows from any other repo's data, seed files, or `.env`.
- If a change would require adding a KINZ-specific concept (a table schema,
  a scraper, a specific threshold), it belongs in the *consuming* repo, not
  here. Add a generic hook/extension point instead.
- Never touch `kinz-price-bridge`'s territory: price normalization, fuzzy
  catalogue matching, or listing→price-feed aggregation. That's a different
  repo's domain logic; this toolkit is what it would be built *on top of*.

## Running things

```bash
pip install -e ".[dev]"
ruff check .                                   # lint
pytest --cov=astk --cov-report=term-missing    # tests + coverage
streamlit run examples/demo_app.py             # manual smoke test of the dashboard helpers
astk doctor --database-url sqlite:////tmp/x.db # manual smoke test of the CLI
```

## Conventions

- `src/` layout; the importable package is `astk`, the PyPI/repo name is
  `analytics-service-toolkit`.
- Every public function/class needs a docstring explaining *why* it exists,
  not just what it does — this library only earns its place if the reason
  for extracting something is legible to whoever adopts it next.
- Streamlit is optional (`astk[streamlit]`). Any function that calls into
  `streamlit` must go through `_require_streamlit()` first and live in
  `astk/dashboard.py`. Pure logic (formatting, thresholds) that dashboard
  code needs should be a plain function, tested without a Streamlit runtime.
- Notifiers must never raise into the caller — return a failed `AlertResult`
  instead. A broken alert channel must not take down the service using it.
- New modules should ask: "do at least two of the KINZ services already
  duplicate this?" If not, it likely doesn't belong here yet — note it in
  `docs/IMPROVEMENTS.md` instead of building it speculatively.

## Backlog

See [docs/IMPROVEMENTS.md](docs/IMPROVEMENTS.md) — ranked, with reasons. The
portfolio's closed loop works this list; keep it accurate as items land.
