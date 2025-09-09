from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvSettings(BaseSettings):
    HAR_USERNAME: Optional[str] = None
    HAR_PASSWORD: Optional[str] = None
    MAPTILER_API_KEY: Optional[str] = None
    HEADLESS: Optional[bool] = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


class Settings(BaseModel):
    project: dict
    paths: dict
    etl: dict
    playwright: dict
    limits: dict
    env: EnvSettings


def load_settings(config_path: str = "config/settings.yaml") -> Settings:
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    env = EnvSettings()  # pulls from .env if present
    cfg["env"] = env
    return Settings(**cfg)
