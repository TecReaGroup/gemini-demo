from pathlib import Path

import pytest

from gemini_demo.client import (
    GeminiProxyClient,
    ProxyRequestError,
    RequestStrategy,
    audio_format,
    detect_audio_mime_type,
    extract_response_text,
    load_lyric_prompt,
    validate_lyric_prompt,
    validate_transcription,
)
from gemini_demo.config import Settings, read_env_file


def test_read_env_file(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('url="https://proxy.example"\nkey=secret\n# ignored\n', encoding="utf-8")

    assert read_env_file(env_path) == {"url": "https://proxy.example", "key": "secret"}


def test_m4a_mime_and_format() -> None:
    assert detect_audio_mime_type(Path("song.m4a")) == "audio/mp4"
    assert audio_format("audio/mp4") == "m4a"


def test_build_input_audio_request() -> None:
    client = GeminiProxyClient(Settings("https://proxy.example", "secret"), "LRC PROMPT")

    endpoint, payload, headers = client._build_request(
        "YWJj", "audio/mp4", RequestStrategy.INPUT_AUDIO
    )

    media_block = payload["messages"][0]["content"][1]
    assert endpoint == "https://proxy.example/v1/chat/completions"
    assert media_block == {
        "type": "input_audio",
        "input_audio": {"data": "YWJj", "format": "m4a"},
    }
    assert payload["messages"][0]["content"][0]["text"] == "LRC PROMPT"
    assert headers["Authorization"] == "Bearer secret"


def test_build_image_url_request() -> None:
    client = GeminiProxyClient(Settings("https://proxy.example", "secret"), "LRC PROMPT")

    _, payload, _ = client._build_request("YWJj", "audio/mp4", RequestStrategy.IMAGE_URL)

    assert payload["messages"][0]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:audio/mp4;base64,YWJj"},
    }


def test_build_native_inline_request() -> None:
    client = GeminiProxyClient(
        Settings("https://proxy.example", "secret", model="gemini-test"), "LRC PROMPT"
    )

    endpoint, payload, headers = client._build_request(
        "YWJj", "audio/mp4", RequestStrategy.NATIVE_INLINE
    )

    assert endpoint == "https://proxy.example/v1beta/models/gemini-test:generateContent"
    assert payload["contents"][0]["parts"][0]["text"] == "LRC PROMPT"
    assert payload["contents"][0]["parts"][1] == {
        "inline_data": {"mime_type": "audio/mp4", "data": "YWJj"}
    }
    assert headers["x-goog-api-key"] == "secret"


@pytest.mark.parametrize(
    ("strategy", "payload", "expected"),
    [
        (
            RequestStrategy.INPUT_AUDIO,
            {"choices": [{"message": {"content": "第一句\n第二句"}}]},
            "第一句\n第二句",
        ),
        (
            RequestStrategy.NATIVE_INLINE,
            {"candidates": [{"content": {"parts": [{"text": "歌词"}]}}]},
            "歌词",
        ),
    ],
)
def test_extract_response_text(strategy, payload, expected) -> None:
    assert extract_response_text(payload, strategy) == expected


def test_extract_response_text_rejects_unknown_shape() -> None:
    with pytest.raises(ProxyRequestError):
        extract_response_text({"error": "bad request"}, RequestStrategy.INPUT_AUDIO)


def test_validate_transcription_rejects_ignored_audio() -> None:
    with pytest.raises(ProxyRequestError, match="audio block was ignored"):
        validate_transcription("您好，您似乎忘记上传音频了。")


def test_validate_transcription_accepts_lyrics() -> None:
    validate_transcription("亲爱的宝贵耶稣\n一生爱你")



def test_load_lyric_prompt(tmp_path: Path) -> None:
    prompt_path = tmp_path / "lyris.md"
    prompt_path.write_text("\n# LRC prompt\n", encoding="utf-8")

    assert load_lyric_prompt(prompt_path) == "# LRC prompt"


def test_validate_lyric_prompt_rejects_empty_content() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        validate_lyric_prompt("  \n")

