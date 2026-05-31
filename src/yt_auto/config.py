"""Application settings loaded from environment / .env file."""
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    gemini_api_key: str = Field(..., description="Google AI Studio / Gemini API key")
    gemini_model: str = Field(default="gemini-2.5-flash")

    # App
    data_dir: Path = Field(default=Path("./data"))
    outputs_dir: Path = Field(default=Path("./outputs"))
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
