"""Environment-backed settings, validated by pydantic.

Secrets are read from the environment only, and there are no defaults for them:
a missing or empty required variable raises at startup and names the variable,
so the process refuses to boot rather than failing later with a confusing auth
error deep inside the driver.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import ConfigurationError

_ALLOWED_SCHEMES = ("bolt://", "bolt+s://", "bolt+ssc://", "neo4j://", "neo4j+s://", "neo4j+ssc://")


class Settings(BaseSettings):
    """Typed application settings, sourced from the environment or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- CognoDB connection. Paste the URI exactly as the console gives it. ---
    cognodb_uri: str = Field(..., description="bolt+s://<instance-id>.databases.cognodb.com")
    cognodb_user: str = Field(..., min_length=1)
    cognodb_password: SecretStr = Field(..., min_length=1)

    # --- Identity token signing key (see app/security). ---
    jwt_secret: SecretStr = Field(..., min_length=16)

    # --- Operational knobs, all with safe defaults. ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    query_timeout_s: Annotated[float, Field(gt=0, le=60)] = 10.0

    #: Hard ceiling on variable-length traversal. Also the bound enforced on
    #: user-supplied hop counts -- an unbounded pattern would hang the demo.
    max_hops: Annotated[int, Field(ge=1, le=6)] = 5

    #: Rows returned by any single list query.
    result_limit: Annotated[int, Field(ge=1, le=100)] = 10

    #: Person the app views the graph as when no valid identity token is present.
    default_person_id: str = "me"

    @field_validator("cognodb_uri")
    @classmethod
    def _check_scheme(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(_ALLOWED_SCHEMES):
            raise ValueError(
                f"unrecognised scheme in {v!r}; expected one of {', '.join(_ALLOWED_SCHEMES)}. "
                "Paste the URI exactly as the CognoDB console gives it."
            )
        return v

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v: object) -> object:
        return v.upper() if isinstance(v, str) else v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build and validate settings once per process.

    Raises:
        ConfigurationError: with a message naming every variable that failed.
    """
    try:
        return Settings()  # type: ignore[call-arg]  # values come from the environment
    except ValidationError as exc:
        problems = "\n".join(
            f"  - {'.'.join(str(p) for p in err['loc']).upper()}: {err['msg']}"
            for err in exc.errors()
        )
        raise ConfigurationError(
            "Invalid configuration. Copy .env.example to .env and fill it in.\n" + problems
        ) from exc
