"""Common settings base class for KINZ-style Python services.

Every service in this portfolio currently hand-rolls its own `.env` loading
with `pydantic`. This module gives them a shared base with the fields that
show up in all of them (app name, env, log level, database URL, Slack
webhook) plus a `load_settings()` helper that turns pydantic's validation
errors into a message a human can act on without reading a traceback.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import PostgresDsn, SecretStr, TypeAdapter, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Reused to validate Postgres URLs while still accepting sqlite:// — see
# BaseServiceSettings.database_url below.
_POSTGRES_DSN = TypeAdapter(PostgresDsn)

T = TypeVar("T", bound="BaseServiceSettings")

_REDACTED = "***"


class SettingsError(Exception):
    """Raised by :func:`load_settings` with a human-readable summary of what's wrong.

    Wraps the underlying ``pydantic.ValidationError`` (available as
    ``__cause__``) so callers who want the raw error details still have them.
    """


class BaseServiceSettings(BaseSettings):
    """Fields every service needs. Subclass and add service-specific fields.

    Example:
        class MyServiceSettings(BaseServiceSettings):
            app_name: str = "margin-guardian"
            shopify_api_key: str

        settings = load_settings(MyServiceSettings)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "service"
    env: Literal["dev", "staging", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # A plain str, not PostgresDsn: these services run Postgres in prod but SQLite
    # in tests (and astk.db.make_engine is SQLite-safe by design). A PostgresDsn
    # field would reject `sqlite:///…` at load time and force every consumer to
    # override it. The validator below keeps the readable Postgres error for the
    # common case while letting sqlite (and other schemes) through.
    database_url: str | None = None
    slack_webhook_url: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def _accept_sqlite_or_validate_postgres(cls, v: str | None) -> str | None:
        if v is None or v.startswith("sqlite"):
            return v
        if v.startswith(("postgresql", "postgres")):
            # Reuse pydantic's PostgresDsn validation for its readable error,
            # but return the original string so SQLAlchemy gets exactly what the
            # user set (PostgresDsn normalisation can append a trailing slash).
            _POSTGRES_DSN.validate_python(v)
        return v

    def __repr__(self) -> str:
        parts = []
        for name in type(self).model_fields:
            value = getattr(self, name)
            if name == "database_url" and value is not None:
                value = _redact_dsn(str(value))
            elif name == "slack_webhook_url" and value is not None:
                value = _REDACTED
            parts.append(f"{name}={value!r}")
        return f"{type(self).__name__}({', '.join(parts)})"

    def dsn(self) -> str:
        """Return the database URL as a plain connection string ready for ``make_engine``.

        Exists because ``database_url`` is a ``PostgresDsn | None``: ``str()`` on an
        unset value yields the literal ``"None"`` (which ``create_engine`` then chokes
        on with an opaque message), and callers otherwise have to remember the field is
        optional. This raises a readable :class:`SettingsError` instead.
        """
        if self.database_url is None:
            raise SettingsError(
                f"{type(self).__name__}.dsn() called but database_url is not set "
                "(set the DATABASE_URL environment variable or the database_url field)"
            )
        return str(self.database_url)

    def slack_webhook(self) -> str | None:
        """Return the real Slack webhook URL, or ``None`` if none is configured.

        Exists because ``slack_webhook_url`` is a ``SecretStr``: in pydantic v2
        ``str(secret)`` returns the mask ``"**********"``, not the URL, so the obvious
        ``SlackNotifier(str(settings.slack_webhook_url))`` silently builds a notifier
        that can never deliver. Call this instead — it unwraps the secret.
        """
        if self.slack_webhook_url is None:
            return None
        return self.slack_webhook_url.get_secret_value()


def _redact_dsn(dsn: str) -> str:
    """Replace the password segment of a DSN with '***', leaving the rest readable."""
    return re.sub(r"://([^:/@\s]+):([^@\s]+)@", r"://\1:***@", dsn)


def load_settings(cls: type[T], env_file: str | Path = ".env") -> T:
    """Instantiate ``cls`` from the environment / an env file.

    Raises :class:`SettingsError` with a readable summary (missing vars,
    invalid values) instead of letting a raw ``pydantic.ValidationError``
    escape. This is the function every service's ``config.py`` should call
    instead of ``MySettings()`` directly.
    """
    try:
        return cls(_env_file=env_file)  # type: ignore[call-arg]
    except ValidationError as exc:
        missing: list[str] = []
        invalid: list[str] = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err["loc"])
            if err["type"] == "missing":
                missing.append(loc)
            else:
                invalid.append(f"{loc}: {err['msg']}")

        lines = [f"Invalid configuration for {cls.__name__} (from {env_file}):"]
        if missing:
            lines.append("  missing required variables: " + ", ".join(missing))
        if invalid:
            lines.append("  invalid values:")
            lines.extend(f"    - {item}" for item in invalid)
        raise SettingsError("\n".join(lines)) from exc
