"""Command-line interface for audio lyric transcription tests."""

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
    Settings,
)
from gemini_demo.logging import configure_logging

AUTO_STRATEGIES = (
    RequestStrategy.IMAGE_URL,
    RequestStrategy.NATIVE_INLINE,
    RequestStrategy.INPUT_AUDIO,
)


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="gemini-demo",
        description="Test Gemini proxy multimodal formats and transcribe song lyrics.",
    )
    parser.add_argument("audio", nargs="?", type=Path, help="Audio file; defaults to data/audio/*")
    parser.add_argument(
        "--strategy",
        choices=("auto", *(strategy.value for strategy in RequestStrategy)),
        default="auto",
        help="Request shape to test; auto stops at the first successful strategy.",
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run one or more multimodal request strategies."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    arguments = build_parser().parse_args(argv)
    logger = configure_logging(DEFAULT_LOG_DIRECTORY, arguments.verbose)

    try:
        settings = Settings.load()
        audio_path = arguments.audio or find_default_audio()
        lyric_prompt = load_lyric_prompt(DEFAULT_LYRIC_PROMPT_PATH)
    except (OSError, ValueError) as exc:
        logger.error("configuration_failed: %s", exc)
        return 2

    strategies = (
        AUTO_STRATEGIES
        if arguments.strategy == "auto"
        else (RequestStrategy(arguments.strategy),)
    )
    client = GeminiProxyClient(settings, lyric_prompt)
    logger.info(
        "transcription_started: audio=%s bytes=%d model=%s prompt=%s strategies=%s",
        audio_path,
        audio_path.stat().st_size,
        settings.model,
        DEFAULT_LYRIC_PROMPT_PATH,
        ",".join(strategy.value for strategy in strategies),
    )

    for strategy in strategies:
        logger.info("strategy_started: strategy=%s", strategy.value)
        try:
            lyrics = client.transcribe(audio_path, strategy)
        except (OSError, ProxyRequestError, ValueError) as exc:
            logger.warning("strategy_failed: strategy=%s error=%s", strategy.value, exc)
            continue

        DEFAULT_LYRIC_DIRECTORY.mkdir(parents=True, exist_ok=True)
        lyric_path = DEFAULT_LYRIC_DIRECTORY / f"{audio_path.stem}_{strategy.value}_lyrics.txt"
        lyric_path.write_text(lyrics + "\n", encoding="utf-8")
        logger.info(
            "strategy_succeeded: strategy=%s characters=%d output=%s",
            strategy.value,
            len(lyrics),
            lyric_path,
        )
        print(lyrics)
        return 0

    logger.error("transcription_failed: no request strategy succeeded")
    return 1








