"""Minimal example wiring together every astk module against a seeded
in-memory SQLite database. No real service or business data involved.

Run with:
    streamlit run examples/demo_app.py
"""

from __future__ import annotations

from sqlalchemy import text

from astk.dashboard import KPI, data_table, health_gauge, kpi_row, page_header, timeseries
from astk.db import fetch_df, make_engine

engine = make_engine("sqlite:///:memory:")

with engine.begin() as conn:
    conn.execute(text("CREATE TABLE demo_margin_history (day TEXT, margin REAL)"))
    seed_rows = [
        ("2026-08-15", 0.22),
        ("2026-08-16", 0.19),
        ("2026-08-17", 0.24),
        ("2026-08-18", 0.21),
        ("2026-08-19", 0.23),
    ]
    for day, margin in seed_rows:
        conn.execute(
            text("INSERT INTO demo_margin_history (day, margin) VALUES (:day, :margin)"),
            {"day": day, "margin": margin},
        )

page_header(
    "astk demo — synthetic margin dashboard",
    subtitle="Fictional data. Not a real service.",
    env_badge="dev",
)

df = fetch_df(engine, "SELECT * FROM demo_margin_history ORDER BY day")

kpi_row(
    [
        KPI(label="Latest margin", value=df.iloc[-1]["margin"], fmt="percent"),
        KPI(label="5-day average", value=df["margin"].mean(), fmt="percent"),
    ]
)

health_gauge(df.iloc[-1]["margin"], thresholds=(0.10, 0.20), label="Margin health")
timeseries(df, x="day", y="margin")
data_table(df)
