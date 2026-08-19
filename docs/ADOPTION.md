# Adoption guide

What each KINZ service currently hand-rolls, and what it would delete by
depending on `astk` instead. This is written from the outside — based on each
repo's README and file layout, not by editing those repos (this toolkit only
creates; it never modifies an existing repo). Treat the "before" column as a
best-effort read, not a guaranteed line-for-line diff.

## kinz-margin-guardian-pipeline

| Concern | Before (hand-rolled) | After (`astk`) |
|---|---|---|
| Settings | Its own pydantic settings class for DB URL, Slack webhook, thresholds | Subclass `astk.settings.BaseServiceSettings`, keep only threshold-specific fields |
| DB | Its own SQLAlchemy engine + session setup in `api/database.py` | `astk.db.make_engine` + `astk.db.session_scope` |
| Alerting | Slack webhook POST logic in the Airflow DAG's `send_slack_alert` task, presumably without retry/backoff | `astk.alerts.SlackNotifier` (retry/backoff, never raises) + `astk.alerts.Deduplicator` so a margin that stays low across DAG runs doesn't alert every run |
| Dashboard | Margin Health Gauge, Margin Erosion Timeline built directly in Streamlit | `astk.dashboard.health_gauge` + `astk.dashboard.timeseries` |

## kinz-competitor-intelligence

| Concern | Before | After |
|---|---|---|
| Settings | `.env` loading for DB/API keys per its own `CONTEXT.md`-documented config | `BaseServiceSettings` subclass |
| DB | Local DB connection handling in `api/` and `dashboard/` | `astk.db` |
| Dashboard | Editable Streamlit tables ("every field editable by hand") | `astk.dashboard.data_table(df, editable=True)` |

## kinz-secure-commerce-hub

Mostly TypeScript/Next.js on the frontend, so `astk` (Python) only applies to
its FastAPI + ETL side — the nightly reconciliation job and any operational
alerting it grows. Lower overlap than the other three; adopt opportunistically
rather than as a priority.

## kinz-accounting-analysis-*

| Concern | Before | After |
|---|---|---|
| Settings | Odoo connection config, presumably ad hoc | `BaseServiceSettings` subclass with an `odoo_url` field added |
| Dashboard | Its own Streamlit dashboard over `analysis/`, `audit/`, `compliance/` outputs | `astk.dashboard` chrome for the KPI/table parts |

## What adoption does *not* mean

This toolkit does not get pushed into those repos automatically — this
genesis loop only creates repositories, it never modifies an existing one.
Adopting `astk` in any of the above is a separate, deliberate change to make
in that repo, at a time of the owner's (or the closed loop's) choosing.
