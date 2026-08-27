"""Command-line interface for audio lyric transcription."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from gemini_demo.client import (
    GeminiProxyClient,
    ProxyRequestError,
    RequestStrategy,
    load_lyric_prompt,
)
from gemini_demo.config import (
    DEFAULT_AUDIO_DIRECTORY,
    DEFAULT_LOG_DIRECTORY,
    DEFAULT_LYRIC_DIRECTORY,
    DEFAULT_LYRIC_PROMPT_PATH,
    REQUEST_STRATEGY_CHOICES,
    Settings,
)
from gemini_demo.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="gemini-demo",
        description="Send audio to Gemini and transcribe LRC lyrics.",
    )
    parser.add_argument("audio", nargs="?", type=Path, help="Audio file; defaults to data/audio/*")
    parser.add_argument(
        "--strategy",
        choices=sorted(REQUEST_STRATEGY_CHOICES),
        help="Override config/config.toml for this execution.",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def find_default_audio(audio_directory: Path = DEFAULT_AUDIO_DIRECTORY) -> Path:
    """Return the sole audio file from the default directory."""
    audio_files = sorted(path for path in audio_directory.iterdir() if path.is_file())
    if not audio_files:
        raise FileNotFoundError(f"No audio file found in {audio_directory}")
    if len(audio_files) > 1:
        names = ", ".join(path.name for path in audio_files)
        raise ValueError(f"Multiple audio files found; specify one explicitly: {names}")
    return audio_files[0]


def lyric_path_for(audio_path: Path) -> Path:
    """Return the LRC output path for an audio file."""
    return DEFAULT_LYRIC_DIRECTORY / f"{audio_path.stem}.lrc"


def main(argv: Sequence[str] | None = None) -> int:
    """Transcribe one audio file with the configured request strategy."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    arguments = build_parser().parse_args(argv)
    logger = configure_logging(DEFAULT_LOG_DIRECTORY, arguments.verbose)

    try:
        settings = Settings.load()
        audio_path = arguments.audio or find_default_audio()
        lyric_prompt = load_lyric_prompt(DEFAULT_LYRIC_PROMPT_PATH)
        request_strategy = RequestStrategy(arguments.strategy or settings.request_strategy)
    except (OSError, ValueError) as exc:
        logger.error("configuration_failed: %s", exc)
        return 2

    client = GeminiProxyClient(settings, lyric_prompt)
    logger.info(
        "transcription_started: audio=%s bytes=%d model=%s prompt=%s strategy=%s",
        audio_path,
        audio_path.stat().st_size,
        settings.model,
        DEFAULT_LYRIC_PROMPT_PATH,
        request_strategy.value,
    )

    try:
        lyrics = client.transcribe(audio_path, request_strategy)
    except (OSError, ProxyRequestError, ValueError) as exc:
        logger.error(
            "transcription_failed: strategy=%s error=%s", request_strategy.value, exc
        )
        return 1

    DEFAULT_LYRIC_DIRECTORY.mkdir(parents=True, exist_ok=True)
    lyric_path = lyric_path_for(audio_path)
    lyric_path.write_text(lyrics + "\n", encoding="utf-8")
    logger.info(
        "transcription_succeeded: strategy=%s characters=%d output=%s",
        request_strategy.value,
        len(lyrics),
        lyric_path,
    )
    print(lyrics)
    return 0
