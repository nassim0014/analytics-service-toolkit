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


#: Default cache lifetime for :func:`cached_query`. Fixed at module scope
#: because ``st.cache_data`` only accepts ``ttl`` at decoration time, not per
#: call — see the note in :func:`cached_query`.
CACHED_QUERY_TTL_S = 60


if _HAS_STREAMLIT:

    @st.cache_data(ttl=CACHED_QUERY_TTL_S, show_spinner=False)
    def _cached_fetch_df(_engine, url: str, sql: str, params: tuple[tuple[str, object], ...]):
        # `_engine` has a leading underscore so st.cache_data skips it when
        # hashing the call (it is unhashable, and `url` already identifies it);
        # `url` + `sql` + `params` are the real, fully-hashable cache key.
        from . import db as _db

        return _db.fetch_df(_engine, sql, dict(params) or None)

else:  # pragma: no cover - exercised via the astk[streamlit] extra

    def _cached_fetch_df(_engine, url, sql, params):
        raise RuntimeError("streamlit is not installed")


def cached_query(engine, sql: str, params: dict[str, object] | None = None):
    """`fetch_df`, wrapped in `st.cache_data` so repeated reruns don't re-hit Postgres.

    The cache is keyed on ``(str(engine.url), sql, params)`` — all hashable — so
    two dashboards pointed at different databases, or the same SQL run with
    different bind parameters, never collide on a stale cached result. The engine
    object is passed straight through (Streamlit ignores the leading-underscore
    parameter it lands in); ``make_engine`` already caches one engine per URL.

    ``ttl`` is fixed at :data:`CACHED_QUERY_TTL_S`: ``st.cache_data`` bakes ``ttl``
    in at decoration time, so it cannot be a per-call argument without recreating
    the cache wrapper on every call — which is exactly the bug this function used
    to have (a fresh closure per invocation, with ``engine`` captured *outside*
    the cache key, so a second engine silently reused the first engine's rows).
    """
    _require_streamlit()
    key_params = tuple(sorted((params or {}).items()))
    return _cached_fetch_df(engine, str(engine.url), sql, key_params)
