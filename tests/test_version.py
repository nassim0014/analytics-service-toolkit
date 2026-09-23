import importlib
import tomllib
from pathlib import Path

import astk


def test_version_matches_pyproject_toml():
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text())

    assert astk.__version__ == pyproject["project"]["version"]


def test_version_is_read_from_metadata_under_the_pip_distribution_name(monkeypatch):
    # The importable package is `astk` but the pip/PyPI distribution name is
    # "analytics-service-toolkit" (pyproject.toml [project].name) — those two
    # numbers happen to be equal ("0.1.0") right now, so a plain equality
    # check against pyproject.toml can't tell "read from metadata" apart from
    # "silently fell back to the hardcoded literal". Pin the actual lookup
    # instead: fail if astk ever queries the wrong distribution name, and
    # confirm the returned value is what ends up on __version__.
    calls = []

    def fake_version(name):
        calls.append(name)
        return "9.9.9-test-sentinel"

    monkeypatch.setattr("importlib.metadata.version", fake_version)
    try:
        importlib.reload(astk)
        assert calls == ["analytics-service-toolkit"]
        assert astk.__version__ == "9.9.9-test-sentinel"
    finally:
        # Undo the patch BEFORE reloading — pytest's own monkeypatch teardown
        # runs after this function returns, so reloading here while the
        # patch is still live would leave __version__ stuck on the sentinel
        # for every later test instead of restoring the real metadata value.
        monkeypatch.undo()
        importlib.reload(astk)


def test_cli_version_command_prints_the_version():
    from typer.testing import CliRunner

    from astk import cli as cli_module

    result = CliRunner().invoke(cli_module.app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == astk.__version__
