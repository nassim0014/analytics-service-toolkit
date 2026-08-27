import pytest

from astk.dashboard import format_value, threshold_color


def test_format_value_currency():
    assert format_value(1234.5, "currency") == "$1,234.50"


def test_format_value_percent():
    assert format_value(0.156, "percent") == "15.6%"


def test_format_value_int():
    assert format_value(42.9, "int") == "43"


def test_threshold_color_below_low():
    assert threshold_color(0.05, (0.1, 0.2)) == "#dc2626"


def test_threshold_color_between():
    assert threshold_color(0.15, (0.1, 0.2)) == "#d97706"


def test_threshold_color_at_or_above_high():
    assert threshold_color(0.2, (0.1, 0.2)) == "#16a34a"
    assert threshold_color(0.25, (0.1, 0.2)) == "#16a34a"


def test_ui_helper_raises_clear_error_without_streamlit():
    astk_dashboard = pytest.importorskip("astk.dashboard")
    if astk_dashboard._HAS_STREAMLIT:
        pytest.skip("streamlit is installed in this environment; nothing to assert here")
    with pytest.raises(RuntimeError, match="streamlit is not installed"):
        astk_dashboard.page_header("title")


def test_demo_app_smoke():
    pytest.importorskip("streamlit")
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    demo_path = Path(__file__).resolve().parent.parent / "examples" / "demo_app.py"
    at = AppTest.from_file(str(demo_path))
    at.run(timeout=15)

    assert not at.exception


# --- cached_query --------------------------------------------------------------
#
# Item 2 in docs/IMPROVEMENTS.md suspected `cached_query` never hit its cache
# across Streamlit reruns (a fresh closure per call). That turns out to be false
# — st.cache_data keys on the wrapped function's module+qualname+source, which
# are stable — but the old code captured `engine` in that closure, *outside* the
# cache key, so a second engine (or, once supported, different bind params)
# silently reused the first call's rows. These tests pin both facts.


class _FakeEngine:
    """Just enough of an Engine for cached_query: a stringifiable `.url`."""

    def __init__(self, url: str):
        self.url = url


@pytest.fixture(autouse=True)
def _clear_streamlit_cache():
    st = pytest.importorskip("streamlit")
    st.cache_data.clear()
    yield
    st.cache_data.clear()


@pytest.fixture
def counting_fetch_df(monkeypatch):
    """Replace astk.db.fetch_df with a call-counting stub."""
    import pandas as pd

    from astk import db

    calls: list[tuple] = []

    def _stub(engine, sql, params=None):
        calls.append((getattr(engine, "url", None), sql, params))
        return pd.DataFrame({"n": [len(calls)]})

    monkeypatch.setattr(db, "fetch_df", _stub)
    return calls


def test_cached_query_reuses_the_cache_on_a_repeated_identical_call(counting_fetch_df):
    from astk.dashboard import cached_query

    engine = _FakeEngine("postgresql://user:***@host/db")

    cached_query(engine, "SELECT 1")
    cached_query(engine, "SELECT 1")

    # The suspected bug: this would be 2 if the cache never hit across reruns.
    assert len(counting_fetch_df) == 1


def test_cached_query_does_not_serve_one_engines_rows_to_another(counting_fetch_df):
    from astk.dashboard import cached_query

    engine_a = _FakeEngine("postgresql://user:***@host-a/db")
    engine_b = _FakeEngine("postgresql://user:***@host-b/db")

    cached_query(engine_a, "SELECT 1")
    cached_query(engine_b, "SELECT 1")

    # Pre-fix, engine was captured outside the cache key, so this was 1 —
    # engine_b silently got engine_a's result.
    assert len(counting_fetch_df) == 2
    assert {row[0] for row in counting_fetch_df} == {
        "postgresql://user:***@host-a/db",
        "postgresql://user:***@host-b/db",
    }


def test_cached_query_keys_on_bind_params(counting_fetch_df):
    from astk.dashboard import cached_query

    engine = _FakeEngine("postgresql://user:***@host/db")

    cached_query(engine, "SELECT * FROM t WHERE org = :org", {"org": 1})
    cached_query(engine, "SELECT * FROM t WHERE org = :org", {"org": 1})
    cached_query(engine, "SELECT * FROM t WHERE org = :org", {"org": 2})

    assert len(counting_fetch_df) == 2
    assert counting_fetch_df[0][2] == {"org": 1}
    assert counting_fetch_df[1][2] == {"org": 2}


def test_cached_query_param_order_does_not_matter_for_the_key(counting_fetch_df):
    from astk.dashboard import cached_query

    engine = _FakeEngine("postgresql://user:***@host/db")

    cached_query(engine, "SELECT 1", {"a": 1, "b": 2})
    cached_query(engine, "SELECT 1", {"b": 2, "a": 1})

    assert len(counting_fetch_df) == 1
