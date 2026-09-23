"""Explicit environment configuration for the EKT AI process."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-luna"
    catalog_mode: Literal["fixture", "live"] = "fixture"
    app_base_url: str = "http://127.0.0.1:8000"
    data_dir: Path = Path("/tmp/ekt-ai")
    action_ttl_seconds: int = 300
    view_ttl_seconds: int = 1800
    llm_timeout_seconds: int = 30
    ekt_timeout_seconds: int = 10
    ekt_api_username: str | None = None
    ekt_api_password: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("CATALOG_MODE", "fixture")
        if mode not in {"fixture", "live"}:
            raise ValueError("CATALOG_MODE must be fixture or live")
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
            catalog_mode=mode,
            app_base_url=os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
            data_dir=Path(os.getenv("EKT_DATA_DIR", "/tmp/ekt-ai")),
            action_ttl_seconds=_int_env("ACTION_TTL_SECONDS", 300),
            view_ttl_seconds=_int_env("VIEW_TTL_SECONDS", 1800),
            llm_timeout_seconds=_int_env("LLM_TIMEOUT_SECONDS", 30),
            ekt_timeout_seconds=_int_env("EKT_TIMEOUT_SECONDS", 10),
            ekt_api_username=os.getenv("EKT_API_USERNAME") or None,
            ekt_api_password=os.getenv("EKT_API_PASSWORD") or None,
        )

    @property
    def backend_dir(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def fixture_catalog_path(self) -> Path:
        return self.backend_dir / "data" / "catalog" / "fixture.json"

    @property
    def conditions_path(self) -> Path:
        return self.backend_dir / "data" / "conditions"

    @property
    def certificates_path(self) -> Path:
        return self.backend_dir / "data" / "certificates"

    @property
    def runtime_dir(self) -> Path:
        return self.data_dir / self.catalog_mode

    @property
    def catalog_db_path(self) -> Path:
        return self.runtime_dir / "catalog.sqlite"

    @property
    def cart_db_path(self) -> Path:
        return self.runtime_dir / "cart.sqlite"
