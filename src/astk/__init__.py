"""astk — Analytics Service Toolkit.

Shared settings, database, alerting, dashboard-chrome, and logging helpers for
the Python data services in this portfolio. See README.md for what this is —
and pointedly what it is not (no business logic, ever).
"""

from importlib.metadata import PackageNotFoundError, version

try:
    # The PyPI/pip distribution name is "analytics-service-toolkit" (see
    # pyproject.toml [project].name) even though the importable package is
    # `astk` — importlib.metadata looks up by distribution name, not import
    # name, so it must match the former.
    __version__ = version("analytics-service-toolkit")
except PackageNotFoundError:
    # Package metadata isn't available (e.g. running from a checkout without
    # `pip install -e .`). Fall back to the pyproject.toml literal so
    # `astk.__version__` still works, without hardcoding a second number that
    # has to be kept in sync by hand once the package is actually installed.
    __version__ = "0.1.0"
