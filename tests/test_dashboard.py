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
