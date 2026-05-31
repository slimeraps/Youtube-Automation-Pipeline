"""Application settings loaded from environment / .env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

VoiceCategory = Literal[
    "calm_narrator",
    "energetic_explainer",
    "deep_documentary",
    "warm_storyteller",
    "mysterious_lowkey",
]


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

    # Voice (ElevenLabs)
    elevenlabs_api_key: str = Field(default="", description="ElevenLabs API key")
    elevenlabs_model: str = Field(default="eleven_multilingual_v2")
    elevenlabs_voice_calm_narrator: str = Field(default="")
    elevenlabs_voice_energetic_explainer: str = Field(default="")
    elevenlabs_voice_deep_documentary: str = Field(default="")
    elevenlabs_voice_warm_storyteller: str = Field(default="")
    elevenlabs_voice_mysterious_lowkey: str = Field(default="")

    # Footage (Pexels)
    pexels_api_key: str = Field(default="")
    pexels_per_page: int = Field(default=10, ge=1, le=80)

    # Captions (faster-whisper)
    whisper_model: str = Field(default="small")
    whisper_device: Literal["cpu", "cuda"] = Field(default="cpu")
    whisper_compute_type: str = Field(default="int8")

    # App
    data_dir: Path = Field(default=Path("./data"))
    outputs_dir: Path = Field(default=Path("./outputs"))
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")

    def elevenlabs_voice_for_category(self, category: str) -> str:
        attr = f"elevenlabs_voice_{category}"
        if not hasattr(self, attr):
            raise KeyError(f"unknown voice category: {category}")
        value: str = getattr(self, attr)
        if not value:
            raise KeyError(f"no voice_id configured for category: {category}")
        return value


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
