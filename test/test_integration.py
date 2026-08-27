import os
from pathlib import Path

import pytest

from gemini_demo.client import GeminiProxyClient, RequestStrategy, load_lyric_prompt
from gemini_demo.config import DEFAULT_LYRIC_PROMPT_PATH, Settings


@pytest.mark.integration
def test_proxy_transcribes_project_audio() -> None:
    if os.getenv("RUN_GEMINI_INTEGRATION") != "1":
        pytest.skip("Set RUN_GEMINI_INTEGRATION=1 to call the configured proxy")

    audio_files = sorted(Path("data/audio").glob("*.m4a"))
    assert audio_files, "Expected an M4A file under data/audio"

    lyrics = GeminiProxyClient(
        Settings.load(), load_lyric_prompt(DEFAULT_LYRIC_PROMPT_PATH)
    ).transcribe(
        audio_files[0], RequestStrategy.IMAGE_URL
    )

    assert len(lyrics) >= 100
    assert "一生爱你" in lyrics
    assert "一生" in lyrics


