from pathlib import Path

import pytest

from yt_auto.config import Settings


def test_settings_loads_required_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("OUTPUTS_DIR", "./outputs")
    monkeypatch.setenv("DATA_DIR", "./data")

    settings = Settings()

    assert settings.gemini_api_key == "fake-key"
    assert settings.gemini_model == "gemini-2.5-flash"  # default
    assert settings.outputs_dir == Path("./outputs")
    assert settings.log_level == "INFO"


def test_settings_missing_required_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(ValueError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_loads_phase2_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_CALM_NARRATOR", "vid-calm")
    monkeypatch.setenv("ELEVENLABS_VOICE_ENERGETIC_EXPLAINER", "vid-energetic")
    monkeypatch.setenv("ELEVENLABS_VOICE_DEEP_DOCUMENTARY", "vid-deep")
    monkeypatch.setenv("ELEVENLABS_VOICE_WARM_STORYTELLER", "vid-warm")
    monkeypatch.setenv("ELEVENLABS_VOICE_MYSTERIOUS_LOWKEY", "vid-myst")
    monkeypatch.setenv("PEXELS_API_KEY", "px-key")

    settings = Settings()

    assert settings.elevenlabs_api_key == "el-key"
    assert settings.elevenlabs_model == "eleven_multilingual_v2"
    assert settings.elevenlabs_voice_for_category("calm_narrator") == "vid-calm"
    assert settings.elevenlabs_voice_for_category("deep_documentary") == "vid-deep"
    assert settings.pexels_api_key == "px-key"
    assert settings.pexels_per_page == 10
    assert settings.whisper_model == "small"
    assert settings.whisper_device == "cpu"
    assert settings.whisper_compute_type == "int8"


def test_settings_voice_for_unknown_category_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_CALM_NARRATOR", "vid")
    monkeypatch.setenv("ELEVENLABS_VOICE_ENERGETIC_EXPLAINER", "vid")
    monkeypatch.setenv("ELEVENLABS_VOICE_DEEP_DOCUMENTARY", "vid")
    monkeypatch.setenv("ELEVENLABS_VOICE_WARM_STORYTELLER", "vid")
    monkeypatch.setenv("ELEVENLABS_VOICE_MYSTERIOUS_LOWKEY", "vid")
    monkeypatch.setenv("PEXELS_API_KEY", "px")

    settings = Settings()

    with pytest.raises(KeyError, match="unknown voice category"):
        settings.elevenlabs_voice_for_category("not_a_category")


def test_settings_loads_phase3_youtube_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el")
    monkeypatch.setenv("ELEVENLABS_VOICE_CALM_NARRATOR", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_ENERGETIC_EXPLAINER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_DEEP_DOCUMENTARY", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_WARM_STORYTELLER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_MYSTERIOUS_LOWKEY", "v")
    monkeypatch.setenv("PEXELS_API_KEY", "p")

    settings = Settings()

    assert settings.youtube_client_secrets_file == Path("./assets/youtube_credentials.json")
    assert settings.youtube_token_file == Path("./assets/youtube_token.json")
    assert settings.youtube_category_id == "22"


def test_settings_youtube_category_id_overrides_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el")
    monkeypatch.setenv("ELEVENLABS_VOICE_CALM_NARRATOR", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_ENERGETIC_EXPLAINER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_DEEP_DOCUMENTARY", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_WARM_STORYTELLER", "v")
    monkeypatch.setenv("ELEVENLABS_VOICE_MYSTERIOUS_LOWKEY", "v")
    monkeypatch.setenv("PEXELS_API_KEY", "p")
    monkeypatch.setenv("YOUTUBE_CATEGORY_ID", "27")

    settings = Settings()

    assert settings.youtube_category_id == "27"
