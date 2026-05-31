import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def narration_fixture() -> dict[str, Any]:
    return json.loads((FIXTURES / "gemini_narration_response.json").read_text())


@pytest.fixture
def scene_visuals_fixture() -> dict[str, Any]:
    return json.loads((FIXTURES / "gemini_scene_visuals_response.json").read_text())
