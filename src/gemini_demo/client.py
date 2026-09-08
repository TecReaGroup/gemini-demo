"""Gemini proxy request strategies and response parsing."""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.request
from enum import StrEnum
from pathlib import Path
from typing import Any

from gemini_demo.config import Settings


LOGGER = logging.getLogger(__name__)
AUDIO_MIME_TYPES = {
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
}
LRC_TIMESTAMP_PATTERN = re.compile(r"\[(\d{2}):(\d{2})\.(\d{2})\]")
LRC_METADATA_PATTERN = re.compile(r"\[(?:ar|al|ti|by|offset|re|ve):[^\]\r\n]*\]")


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
        lyrics = self._post_stream(endpoint, payload, headers, strategy)
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
            "Accept": "text/event-stream",
        }
        if strategy is RequestStrategy.NATIVE_INLINE:
            endpoint = (
                f"{self._settings.base_url}/v1beta/models/"
                f"{self._settings.model}:streamGenerateContent?alt=sse"
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
                ],
                "tools": [{"google_search": {}}],
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
            "temperature": 1,
            "stream": True,
        }
        return endpoint, payload, authorization_headers

    def _post_stream(
        self,
        endpoint: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        strategy: RequestStrategy,
    ) -> str:
        request_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=request_data,
            headers=headers,
            method="POST",
        )
        LOGGER.debug("Sending %d request bytes using %s", len(request_data), strategy)
        text_fragments: list[str] = []
        finish_reason: str | None = None
        event_lines: list[str] = []

        def consume_event() -> bool:
            nonlocal finish_reason
            if not event_lines:
                return False
            data_lines = [line[5:].lstrip() for line in event_lines if line.startswith("data:")]
            event_lines.clear()
            if not data_lines:
                return False
            event_data = "\n".join(data_lines)
            if event_data == "[DONE]":
                return True
            try:
                chunk = json.loads(event_data)
            except json.JSONDecodeError as exc:
                raise ProxyRequestError("Invalid streaming JSON response") from exc
            if not isinstance(chunk, dict):
                return False
            if "error" in chunk:
                raise ProxyRequestError("Streaming API error")
            text_fragments.append(extract_stream_text(chunk, strategy))
            chunk_finish_reason = extract_finish_reason(chunk, strategy)
            if chunk_finish_reason is not None:
                finish_reason = chunk_finish_reason
            log_grounding_metadata(chunk, strategy)
            return False

        try:
            with urllib.request.urlopen(
                request, timeout=self._settings.timeout_seconds
            ) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        if consume_event():
                            break
                        continue
                    if line.startswith(":") or line.startswith(("event:", "id:", "retry:")):
                        continue
                    if line.startswith("data:"):
                        event_lines.append(line)
                else:
                    consume_event()
        except urllib.error.HTTPError as exc:
            exc.close()
            raise ProxyRequestError(f"HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ProxyRequestError("Request failed: network error") from exc

        expected_finish_reason = "STOP" if strategy is RequestStrategy.NATIVE_INLINE else "stop"
        if finish_reason != expected_finish_reason:
            reason = finish_reason or "missing"
            raise ProxyRequestError(f"Rejected incomplete transcription ({reason})")
        return "".join(text_fragments)


def detect_audio_mime_type(audio_path: Path) -> str:
    """Resolve a Gemini-compatible MIME type from an audio file path."""
    mime_type = AUDIO_MIME_TYPES.get(audio_path.suffix.lower())
    if mime_type:
        return mime_type
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


def extract_stream_text(
    response_chunk: dict[str, Any], strategy: RequestStrategy
) -> str:
    """Extract visible text from one SSE chunk while ignoring thinking output."""
    try:
        if strategy is RequestStrategy.NATIVE_INLINE:
            candidates = response_chunk.get("candidates", [])
            if not candidates:
                return ""
            content = candidates[0].get("content", {})
            if not isinstance(content, dict):
                return ""
            parts = content.get("parts", [])
            return "".join(
                part["text"]
                for part in parts
                if isinstance(part, dict)
                and isinstance(part.get("text"), str)
                and not part.get("thought", False)
            )

        choices = response_chunk.get("choices", [])
        if not choices:
            return ""
        choice = choices[0]
        if not isinstance(choice, dict):
            return ""
        delta = choice.get("delta", {})
        if not isinstance(delta, dict):
            return ""
        content = delta.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                block["text"]
                for block in content
                if isinstance(block, dict)
                and isinstance(block.get("text"), str)
                and block.get("type") not in {"thinking", "reasoning"}
            )
    except (IndexError, KeyError, TypeError) as exc:
        raise ProxyRequestError(
            "Unexpected streaming response shape"
        ) from exc
    return ""


def validate_transcription(lyrics: str) -> None:
    """Require nonempty, ordered timestamped LRC lines or metadata tags."""
    if not lyrics or "```" in lyrics:
        raise ProxyRequestError("The proxy returned invalid LRC transcription")
    previous_timestamp = -1
    lyric_line_found = False
    for line in lyrics.splitlines():
        if not line.strip() or line.strip().startswith(("#", "~~~")):
            raise ProxyRequestError("The proxy returned invalid LRC transcription")
        metadata = LRC_METADATA_PATTERN.fullmatch(line.strip())
        if metadata:
            continue
        timestamp_prefix = re.match(r"(?:\[\d{2}:\d{2}\.\d{2}\])+", line)
        if not timestamp_prefix:
            raise ProxyRequestError("The proxy returned invalid LRC transcription")
        timestamps = list(LRC_TIMESTAMP_PATTERN.finditer(timestamp_prefix.group(0)))
        if not line[timestamp_prefix.end():].strip():
            raise ProxyRequestError("The proxy returned invalid LRC transcription")
        lyric_line_found = True
        for timestamp in timestamps:
            minutes, seconds, fraction = timestamp.groups()
            if int(seconds) >= 60:
                raise ProxyRequestError("The proxy returned invalid LRC timestamp")
            current_timestamp = int(minutes) * 60 * 1000 + int(seconds) * 1000 + int(fraction) * 10
            if current_timestamp < previous_timestamp:
                raise ProxyRequestError("The proxy returned non-ordered LRC timestamps")
            previous_timestamp = current_timestamp
    if not lyric_line_found:
        raise ProxyRequestError("The proxy returned invalid LRC transcription")


def extract_finish_reason(response_chunk: dict[str, Any], strategy: RequestStrategy) -> str | None:
    """Read the provider's terminal reason without exposing response content."""
    if strategy is RequestStrategy.NATIVE_INLINE:
        candidates = response_chunk.get("candidates", [])
        return candidates[0].get("finishReason") if candidates and isinstance(candidates[0], dict) else None
    choices = response_chunk.get("choices", [])
    return choices[0].get("finish_reason") if choices and isinstance(choices[0], dict) else None


def log_grounding_metadata(response_chunk: dict[str, Any], strategy: RequestStrategy) -> None:
    """Log only counts from native grounding metadata."""
    if strategy is not RequestStrategy.NATIVE_INLINE:
        return
    candidates = response_chunk.get("candidates", [])
    metadata = (
        candidates[0].get("groundingMetadata", {})
        if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict)
        else {}
    )
    if isinstance(metadata, dict):
        queries = metadata.get("webSearchQueries", [])
        sources = metadata.get("groundingChunks", [])
        LOGGER.debug(
            "Native grounding metadata: %d queries, %d sources",
            len(queries) if isinstance(queries, list) else 0,
            len(sources) if isinstance(sources, list) else 0,
        )




def load_lyric_prompt(prompt_path: Path) -> str:
    """Read and validate the lyric transcription prompt."""
    return validate_lyric_prompt(prompt_path.read_text(encoding="utf-8-sig"))


def validate_lyric_prompt(lyric_prompt: str) -> str:
    """Return a normalized non-empty lyric transcription prompt."""
    normalized_prompt = lyric_prompt.strip()
    if not normalized_prompt:
        raise ValueError("Lyric prompt must not be empty")
    return normalized_prompt
