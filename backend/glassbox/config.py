"""Application settings (environment / .env). Only the API process imports this module."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StartupError(RuntimeError):
    """The configuration is unsafe or invalid; the server must not start."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    host: str = Field("127.0.0.1", validation_alias=AliasChoices("GLASSBOX_HOST", "host"))
    port: int = Field(8000, validation_alias=AliasChoices("GLASSBOX_PORT", "port"))
    allow_remote: bool = Field(False, validation_alias=AliasChoices("GLASSBOX_ALLOW_REMOTE", "allow_remote"))
    sandbox_mode: Literal["subprocess", "docker"] = Field(
        "subprocess", validation_alias=AliasChoices("SANDBOX_MODE", "sandbox_mode")
    )
    docker_image: str = Field("glassbox-runner", validation_alias=AliasChoices("GLASSBOX_DOCKER_IMAGE", "docker_image"))
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        validation_alias=AliasChoices("GLASSBOX_CORS_ORIGINS", "cors_origins"),
    )
    max_concurrent_runs: int = Field(4, ge=1, validation_alias=AliasChoices("GLASSBOX_MAX_RUNS", "max_concurrent_runs"))
    run_store_size: int = Field(20, ge=1, validation_alias=AliasChoices("GLASSBOX_RUN_STORE_SIZE", "run_store_size"))
    run_ttl_s: int = Field(3600, ge=1, validation_alias=AliasChoices("GLASSBOX_RUN_TTL_S", "run_ttl_s"))
    runs_dir: str | None = Field(None, validation_alias=AliasChoices("GLASSBOX_RUNS_DIR", "runs_dir"))
    max_source_kb: int = Field(200, ge=1)
    max_files: int = Field(20, ge=1)
    # --- LLM providers (spec 6.4). Nothing is hardcoded: an unset base URL / model / key list = provider unavailable.
    llm_provider_order: str = "groq,gemini"
    groq_api_keys: str = Field("", repr=False)
    gemini_api_keys: str = Field("", repr=False)
    groq_model: str = ""
    gemini_model: str = ""
    groq_base_url: str = ""
    gemini_base_url: str = ""
    llm_timeout_s: float = Field(30.0, gt=0)
    llm_max_output_tokens: int | None = None
    # strict: every event is validated against the schema (tests); sampled: every 100th (production); off.
    validate_events: Literal["strict", "sampled", "off"] = Field(
        "sampled", validation_alias=AliasChoices("GLASSBOX_VALIDATE_EVENTS", "validate_events")
    )


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def ensure_safe_startup(settings: Settings) -> None:
    """Refuse configurations that expose the subprocess sandbox beyond localhost (docs/SECURITY.md)."""
    if settings.allow_remote and settings.sandbox_mode != "docker":
        raise StartupError(
            "GLASSBOX_ALLOW_REMOTE=true requires SANDBOX_MODE=docker. The subprocess sandbox is not a security "
            "boundary and must never be reachable from other machines. Set SANDBOX_MODE=docker or unset "
            "GLASSBOX_ALLOW_REMOTE."
        )


def bind_host(settings: Settings) -> str:
    """Host to bind: always loopback unless remote access was explicitly (and safely) enabled."""
    return settings.host if settings.allow_remote else "127.0.0.1"
