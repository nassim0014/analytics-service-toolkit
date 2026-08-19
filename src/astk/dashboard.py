"""Streamlit dashboard chrome: KPI rows, health gauges, timeseries charts,
editable tables, sidebar filters — the pieces every service's dashboard
rebuilds from scratch.

Streamlit is an optional dependency (`pip install analytics-service-toolkit[streamlit]`).
The formatting/threshold logic is factored into plain functions
(`format_value`, `threshold_color`) so it's unit-testable without a Streamlit
runtime; the `st.*`-calling functions below need one and raise a clear
`RuntimeError` if streamlit isn't installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

try:
    import streamlit as st

    _HAS_STREAMLIT = True
except ImportError:  # pragma: no cover - exercised via astk[streamlit] extra
    st = None  # type: ignore[assignment]
    _HAS_STREAMLIT = False

Format = Literal["currency", "percent", "int"]


def _require_streamlit() -> None:
    if not _HAS_STREAMLIT:
        raise RuntimeError(
            "streamlit is not installed; install analytics-service-toolkit[streamlit] "
            "to use astk.dashboard UI helpers"
        )


@dataclass
class KPI:
    label: str
    value: float
    delta: float | None = None
    fmt: Format = "int"


def format_value(value: float, fmt: Format) -> str:
    """Pure formatting used both by the UI helpers below and directly in tests."""
    if fmt == "currency":
        return f"${value:,.2f}"
    if fmt == "percent":
        return f"{value:.1%}"
    return f"{value:,.0f}"


def threshold_color(value: float, thresholds: tuple[float, float]) -> str:
    """Red below the low threshold, amber between, green at/above the high one."""
    low, high = thresholds
    if value < low:
        return "#dc2626"
    if value < high:
        return "#d97706"
    return "#16a34a"


def page_header(title: str, subtitle: str | None = None, env_badge: str | None = None) -> None:
    _require_streamlit()
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    if env_badge:
        st.caption(f"env: {env_badge}")


def kpi_row(kpis: list[KPI]) -> None:
    _require_streamlit()
    columns = st.columns(len(kpis))
    for column, kpi in zip(columns, kpis, strict=True):
        column.metric(kpi.label, format_value(kpi.value, kpi.fmt), delta=kpi.delta)


def health_gauge(value: float, thresholds: tuple[float, float], label: str = "Health") -> None:
    _require_streamlit()
    color = threshold_color(value, thresholds)
    st.markdown(f"**{label}**")
    st.progress(min(max(value, 0.0), 1.0))
    st.markdown(
        f"<span style='color:{color}'>{format_value(value, 'percent')}</span>",
        unsafe_allow_html=True,
    )


def timeseries(df, x: str, y: str) -> None:
    _require_streamlit()
    st.line_chart(df, x=x, y=y)


def data_table(df, editable: bool = False):
    _require_streamlit()
    if editable:
        return st.data_editor(df)
    st.dataframe(df)
    return df


def sidebar_filters(options: dict[str, list]) -> dict:
    _require_streamlit()
    result: dict = {}
    with st.sidebar:
        for key, values in options.items():
            result[key] = st.selectbox(key, values)
    return result


def cached_query(engine, sql: str, ttl_s: int = 60):
    """`fetch_df`, wrapped in `st.cache_data` so repeated reruns don't re-hit Postgres."""
    _require_streamlit()
    from . import db as _db

    @st.cache_data(ttl=ttl_s)
    def _run(sql_text: str):
        return _db.fetch_df(engine, sql_text)

    return _run(sql)
