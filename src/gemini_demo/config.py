"""Application configuration."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("config/config.toml")
DEFAULT_AUDIO_DIRECTORY = Path("data/audio")
DEFAULT_LOG_DIRECTORY = Path("log")
DEFAULT_LYRIC_DIRECTORY = Path("data/lyris")
DEFAULT_LYRIC_PROMPT_PATH = Path("data/prompt/lyris.md")
DEFAULT_MODEL = "gemini-3.1-pro-preview"
DEFAULT_REQUEST_STRATEGY = "image-url"
DEFAULT_TIMEOUT_SECONDS = 600
ENV_PATH = Path(".env")
REQUEST_STRATEGY_CHOICES = frozenset({"image-url", "native-inline", "input-audio"})


@dataclass(frozen=True, slots=True)
class Settings:
    """Hold validated runtime settings for the proxy request."""

    base_url: str
    api_key: str
    model: str = DEFAULT_MODEL
    request_strategy: str = DEFAULT_REQUEST_STRATEGY
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def load(
        cls,
        env_path: Path = ENV_PATH,
        config_path: Path = CONFIG_PATH,
    ) -> Settings:
        """Load and validate proxy settings from TOML, environment, and a local env file."""
        file_values = read_env_file(env_path)
        config_sections = read_toml_file(config_path)
        request_section = config_sections.get("request", {})
        if not isinstance(request_section, dict):
            raise ValueError("config.toml [request] must be a table")

        base_url = os.getenv("GEMINI_BASE_URL", file_values.get("url", "")).strip()
        api_key = os.getenv("GEMINI_API_KEY", file_values.get("key", "")).strip()
        configured_model = request_section.get("model", DEFAULT_MODEL)
        model = os.getenv(
            "GEMINI_MODEL", file_values.get("model", str(configured_model))
        ).strip()
        configured_strategy = request_section.get("strategy", DEFAULT_REQUEST_STRATEGY)
        request_strategy = os.getenv(
            "GEMINI_REQUEST_STRATEGY", str(configured_strategy)
        ).strip()

        missing_names = [
            name
            for name, value in (("url/GEMINI_BASE_URL", base_url), ("key/GEMINI_API_KEY", api_key))
            if not value
        ]
        if missing_names:
            raise ValueError(f"Missing configuration: {', '.join(missing_names)}")
        if request_strategy not in REQUEST_STRATEGY_CHOICES:
            choices = ", ".join(sorted(REQUEST_STRATEGY_CHOICES))
            raise ValueError(
                f"Unsupported request strategy '{request_strategy}'. Choose one of: {choices}"
            )

        return cls(
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            model=model,
            request_strategy=request_strategy,
        )


def read_env_file(env_path: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE entries without adding a dotenv dependency."""
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def read_toml_file(config_path: Path) -> dict[str, Any]:
    """Read application settings from a TOML file."""
    if not config_path.exists():
        return {}
    with config_path.open("rb") as config_file:
        return tomllib.load(config_file)
