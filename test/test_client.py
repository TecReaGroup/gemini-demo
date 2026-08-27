from pathlib import Path
import io
import urllib.error

import pytest

from gemini_demo.client import (
    GeminiProxyClient,
    ProxyRequestError,
    RequestStrategy,
    audio_format,
    detect_audio_mime_type,
    extract_response_text,
    extract_stream_text,
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

    assert endpoint == "https://proxy.example/v1beta/models/gemini-test:streamGenerateContent?alt=sse"
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



class FakeStreamingResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode("utf-8") for line in lines]

    def __enter__(self) -> "FakeStreamingResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __iter__(self):
        return iter(self._lines)


def test_build_streaming_image_url_request() -> None:
    client = GeminiProxyClient(Settings("https://proxy.example", "secret"), "LRC PROMPT")

    endpoint, payload, headers = client._build_request(
        "YWJj", "audio/mp4", RequestStrategy.IMAGE_URL
    )

    assert endpoint == "https://proxy.example/v1/chat/completions"
    assert payload["stream"] is True
    assert headers["Accept"] == "text/event-stream"


def test_extract_stream_text_ignores_reasoning_content() -> None:
    chunk = {
        "choices": [
            {
                "delta": {
                    "reasoning_content": "internal reasoning",
                    "content": "[00:01.00] 正式歌词",
                }
            }
        ]
    }

    assert extract_stream_text(chunk, RequestStrategy.IMAGE_URL) == "[00:01.00] 正式歌词"


def test_extract_stream_text_ignores_thought_parts() -> None:
    chunk = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "internal reasoning", "thought": True},
                        {"text": "[00:01.00] 正式歌词"},
                    ]
                }
            }
        ]
    }

    assert extract_stream_text(chunk, RequestStrategy.NATIVE_INLINE) == "[00:01.00] 正式歌词"


def test_post_stream_reads_sse_until_done(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GeminiProxyClient(Settings("https://proxy.example", "secret"), "LRC PROMPT")
    response = FakeStreamingResponse(
        [
            ": keep-alive\n",
            'data: {"choices":[{"delta":{"content":"第一句"}}]}\n',
            '\n',
            'data: {"choices":[{"delta":{"reasoning_content":"ignored"}}]}\n',
            'data: {"choices":[{"delta":{"content":"\\n第二句"}}]}\n',
            "data: [DONE]\n",
        ]
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: response)

    lyrics = client._post_stream(
        "https://proxy.example/v1/chat/completions",
        {"stream": True},
        {"Content-Type": "application/json"},
        RequestStrategy.IMAGE_URL,
    )

    assert lyrics == "第一句\n第二句"





def test_post_stream_reports_http_error_before_sse_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiProxyClient(Settings("https://proxy.example", "secret"), "LRC PROMPT")
    error_body = io.BytesIO(
        b'{"error":{"code":"model_not_found","message":"no distributor"}}'
    )
    http_error = urllib.error.HTTPError(
        "https://proxy.example/v1/chat/completions",
        503,
        "Service Unavailable",
        {},
        error_body,
    )

    def raise_http_error(*args: object, **kwargs: object) -> None:
        raise http_error

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)

    with pytest.raises(ProxyRequestError, match=r"HTTP 503: .*model_not_found"):
        client._post_stream(
            "https://proxy.example/v1/chat/completions",
            {"stream": True},
            {"Content-Type": "application/json"},
            RequestStrategy.IMAGE_URL,
        )
