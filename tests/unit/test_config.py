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
