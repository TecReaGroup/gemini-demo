import json
import os
from pathlib import Path
import urllib.request

import pytest

from gemini_demo.client import GeminiProxyClient, RequestStrategy, load_lyric_prompt
from gemini_demo.config import DEFAULT_LYRIC_PROMPT_PATH, Settings


DATE_PROMPT = "What is today's date? Reply with the current date and a short explanation of how you know it."


def post_date_request(settings: Settings) -> list[dict[str, object]]:
    """Ask the configured model for its current date and return response chunks."""
    endpoint = (
        f"{settings.base_url}/v1beta/models/"
        f"{settings.model}:streamGenerateContent?alt=sse"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": DATE_PROMPT}]}],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "x-goog-api-key": settings.api_key,
        },
        method="POST",
    )

    response_chunks: list[dict[str, object]] = []
    with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if line == "[DONE]":
                break
            response_chunk = json.loads(line)
            if isinstance(response_chunk, dict):
                response_chunks.append(response_chunk)

    return response_chunks


def collect_response_text(response_chunks: list[dict[str, object]]) -> str:
    """Collect visible text from native Gemini response chunks."""
    text_fragments: list[str] = []
    for response_chunk in response_chunks:
        candidates = response_chunk.get("candidates", [])
        if not isinstance(candidates, list) or not candidates:
            continue
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content", {})
        if not isinstance(content, dict):
            continue
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            continue
        text_fragments.extend(
            part["text"]
            for part in parts
            if isinstance(part, dict)
            and isinstance(part.get("text"), str)
            and not part.get("thought", False)
        )
    return "".join(text_fragments)


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


@pytest.mark.integration
def test_proxy_reports_model_date() -> None:
    if os.getenv("RUN_GEMINI_INTEGRATION") != "1":
        pytest.skip("Set RUN_GEMINI_INTEGRATION=1 to call the configured proxy")

    response_chunks = post_date_request(Settings.load())
    answer = collect_response_text(response_chunks)

    assert answer, (
        "Expected a text answer from the model. "
        f"Response: {json.dumps(response_chunks, ensure_ascii=False)[:4000]}"
    )
    print("\n--- model date response ---")
    print(answer)