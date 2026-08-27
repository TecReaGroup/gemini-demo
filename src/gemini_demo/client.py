"""Gemini proxy request strategies and response parsing."""

from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.request
from enum import StrEnum
from pathlib import Path
from typing import Any

from gemini_demo.config import Settings


class RequestStrategy(StrEnum):
    """Represent one proxy-compatible multimodal request shape."""

    INPUT_AUDIO = "input-audio"
    IMAGE_URL = "image-url"
    NATIVE_INLINE = "native-inline"


class ProxyRequestError(RuntimeError):
    """Report a non-successful or malformed proxy response."""


class GeminiProxyClient:
    """Send audio to a Gemini proxy using its common request formats."""

    def __init__(self, settings: Settings, lyric_prompt: str) -> None:
        """Create a client from validated runtime settings."""
        self._settings = settings
        self._lyric_prompt = validate_lyric_prompt(lyric_prompt)

    def transcribe(self, audio_path: Path, strategy: RequestStrategy) -> str:
        """Transcribe one audio file with the selected request strategy."""
        audio_bytes = audio_path.read_bytes()
        encoded_audio = base64.b64encode(audio_bytes).decode("ascii")
        mime_type = detect_audio_mime_type(audio_path)
        endpoint, payload, headers = self._build_request(
            encoded_audio=encoded_audio,
            mime_type=mime_type,
            strategy=strategy,
        )
        response_payload = self._post_json(endpoint, payload, headers)
        lyrics = extract_response_text(response_payload, strategy)
        normalized_lyrics = lyrics.strip()
        validate_transcription(normalized_lyrics)
        return normalized_lyrics

    def _build_request(
        self,
        encoded_audio: str,
        mime_type: str,
        strategy: RequestStrategy,
    ) -> tuple[str, dict[str, Any], dict[str, str]]:
        authorization_headers = {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Content-Type": "application/json",
        }
        if strategy is RequestStrategy.NATIVE_INLINE:
            endpoint = (
                f"{self._settings.base_url}/v1beta/models/"
                f"{self._settings.model}:generateContent"
            )
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": self._lyric_prompt},
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": encoded_audio,
                                }
                            },
                        ],
                    }
                ]
            }
            return endpoint, payload, {
                **authorization_headers,
                "x-goog-api-key": self._settings.api_key,
            }

        endpoint = f"{self._settings.base_url}/v1/chat/completions"
        if strategy is RequestStrategy.INPUT_AUDIO:
            media_block: dict[str, Any] = {
                "type": "input_audio",
                "input_audio": {
                    "data": encoded_audio,
                    "format": audio_format(mime_type),
                },
            }
        else:
            media_block = {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{encoded_audio}"},
            }

        payload = {
            "model": self._settings.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._lyric_prompt},
                        media_block,
                    ],
                }
            ],
            "temperature": 0,
        }
        return endpoint, payload, authorization_headers

    def _post_json(
        self,
        endpoint: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._settings.timeout_seconds
            ) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise ProxyRequestError(f"HTTP {exc.code}: {error_body[:1000]}") from exc
        except urllib.error.URLError as exc:
            raise ProxyRequestError(f"Request failed: {exc.reason}") from exc

        try:
            response_payload = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise ProxyRequestError(f"Invalid JSON response: {response_body[:1000]}") from exc
        if not isinstance(response_payload, dict):
            raise ProxyRequestError("Expected a JSON object response")
        return response_payload


def detect_audio_mime_type(audio_path: Path) -> str:
    """Resolve a Gemini-compatible MIME type from an audio file path."""
    extension_overrides = {
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
    }
    mime_type = extension_overrides.get(audio_path.suffix.lower())
    if mime_type:
        return mime_type
    guessed_type, _ = mimetypes.guess_type(audio_path.name)
    if guessed_type and guessed_type.startswith("audio/"):
        return guessed_type
    raise ValueError(f"Unsupported audio extension: {audio_path.suffix or '<none>'}")


def audio_format(mime_type: str) -> str:
    """Map an audio MIME type to the OpenAI-compatible format token."""
    return {
        "audio/aac": "aac",
        "audio/flac": "flac",
        "audio/mp4": "m4a",
        "audio/mpeg": "mp3",
        "audio/ogg": "ogg",
        "audio/wav": "wav",
    }[mime_type]


def extract_response_text(
    response_payload: dict[str, Any], strategy: RequestStrategy
) -> str:
    """Extract generated text from OpenAI-compatible or native Gemini JSON."""
    try:
        if strategy is RequestStrategy.NATIVE_INLINE:
            parts = response_payload["candidates"][0]["content"]["parts"]
            return "\n".join(
                part["text"] for part in parts if isinstance(part.get("text"), str)
            )

        content = response_payload["choices"][0]["message"]["content"]
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                block["text"]
                for block in content
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            )
    except (IndexError, KeyError, TypeError) as exc:
        raise ProxyRequestError(
            f"Unexpected response shape: {json.dumps(response_payload, ensure_ascii=False)[:1000]}"
        ) from exc
    raise ProxyRequestError(
        f"Unexpected response content: {json.dumps(response_payload, ensure_ascii=False)[:1000]}"
    )


def validate_transcription(lyrics: str) -> None:
    """Reject empty output and common proxy responses that ignored the audio block."""
    if not lyrics:
        raise ProxyRequestError("The proxy returned no transcription text")

    missing_audio_phrases = (
        "忘记上传",
        "没有上传",
        "未上传",
        "无法访问音频",
        "无法读取音频",
        "provide the audio",
        "attach the audio",
        "no audio",
    )
    normalized_text = lyrics.casefold()
    if any(phrase in normalized_text for phrase in missing_audio_phrases):
        raise ProxyRequestError("The model response indicates that the audio block was ignored")




def load_lyric_prompt(prompt_path: Path) -> str:
    """Read and validate the lyric transcription prompt."""
    return validate_lyric_prompt(prompt_path.read_text(encoding="utf-8-sig"))


def validate_lyric_prompt(lyric_prompt: str) -> str:
    """Return a normalized non-empty lyric transcription prompt."""
    normalized_prompt = lyric_prompt.strip()
    if not normalized_prompt:
        raise ValueError("Lyric prompt must not be empty")
    return normalized_prompt
