# config.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Iterator, Any
import os

import yaml
from pydantic import BaseModel, Field, AliasChoices, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict


# -------- Environment (.env / process env) --------

class EnvSettings(BaseSettings):
    HAR_USERNAME: Optional[str] = None
    HAR_PASSWORD: Optional[str] = None
    MAPTILER_API_KEY: Optional[str] = None
    HEADLESS: Optional[bool] = True

    # read .env; forbid typos
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    # alias DATABASE_URL (either name works)
    database_url: str = Field(
        validation_alias=AliasChoices("DATABASE_URL", "database_url")
    )


# -------- Typed ETL config (dict-like for backward compatibility) --------

class CsvConfig(BaseModel):
    delimiter: str = ","
    quotechar: str = '"'
    encoding: str = "utf-8"
    strict: bool = True
    model_config = ConfigDict(extra="allow")


class ZipNormalization(BaseModel):
    invalid_zip5: List[str] = ["00000"]
    model_config = ConfigDict(extra="allow")


class EtlConfig(BaseModel):
    batch_size: int = 100
    concurrency: int = 3
    delay_ms_between_requests: int = 500
    user_agent: Optional[str] = "relml-bot"

    # REQUIRED — set in settings.yaml
    required_headers: List[str]

    # Optional header synonyms
    header_aliases: Dict[str, str] = {}

    csv: CsvConfig = CsvConfig()
    zip_normalization: ZipNormalization = ZipNormalization()

    # allow future keys without breaking
    model_config = ConfigDict(extra="allow")

    # --- dict-like shims so old code using S.etl["..."] keeps working ---
    def __getitem__(self, key: str) -> Any:
        return self.model_dump().get(key)

    def get(self, key: str, default: Any = None) -> Any:
        return self.model_dump().get(key, default)

    def keys(self) -> Iterator[str]:
        return iter(self.model_dump().keys())

    def __iter__(self) -> Iterator[str]:
        return self.keys()

    def __len__(self) -> int:
        return len(self.model_dump())


# -------- Top-level settings aggregate --------

class Settings(BaseModel):
    # keep other sections loose (typed later if needed)
    project: Optional[dict] = None
    paths: Optional[dict] = None
    etl: EtlConfig
    playwright: Optional[dict] = None
    limits: Optional[dict] = None
    env: EnvSettings

    model_config = ConfigDict(extra="allow")


# -------- Loader --------

def _candidate_paths() -> List[Path]:
    """
    Resolution order if no explicit path is passed:
    1) RELML_SETTINGS
    2) ./settings.yaml
    3) ./config/settings.yaml
    """
    env = os.getenv("RELML_SETTINGS")
    if env:
        return [Path(env)]
    return [Path("settings.yaml"), Path("config/settings.yaml")]


def load_settings(config_path: str | None = "config/settings.yaml") -> Settings:
    """
    Load typed settings from YAML, merge .env/env vars, and validate etl knobs.
    Backward-compatible: accepts an explicit config_path like before.
    """
    # If caller passed a path, prefer it; otherwise use the candidate list.
    paths = [Path(config_path)] if config_path else _candidate_paths()

    last_err: Optional[Exception] = None
    for p in paths:
        try:
            if not p.exists():
                continue
            with p.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            # Validate ETL section presence
            if "etl" not in raw:
                raise ValueError(f"Missing 'etl' section in settings file: {p}")
            if "required_headers" not in raw["etl"]:
                raise ValueError(f"Missing 'etl.required_headers' in settings file: {p}")

            env = EnvSettings()  # pulls from .env and process env
            raw["env"] = env
            return Settings(**raw)
        except Exception as e:
            last_err = e
            continue

    # If we’re here, nothing loaded
    tried = ", ".join(str(x) for x in paths)
    hint = f"Tried: {tried}. Set RELML_SETTINGS or pass config_path to load_settings()."
    if last_err:
        raise FileNotFoundError(f"Failed to load settings.yaml. {hint}") from last_err
    raise FileNotFoundError(f"No settings.yaml found. {hint}")
