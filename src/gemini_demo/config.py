"""Application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_AUDIO_DIRECTORY = Path("data/audio")
DEFAULT_LOG_DIRECTORY = Path("log")
DEFAULT_MODEL = "gemini-3.1-pro-preview"
DEFAULT_LYRIC_PROMPT_PATH = Path("data/prompt/lyris.md")
DEFAULT_LYRIC_DIRECTORY = Path("data/lyris")
DEFAULT_TIMEOUT_SECONDS = 600
ENV_PATH = Path(".env")


@dataclass(frozen=True, slots=True)
class Settings:
    """Hold validated runtime settings for the proxy request."""

    base_url: str
    api_key: str
    model: str = DEFAULT_MODEL
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def load(cls, env_path: Path = ENV_PATH) -> Settings:
        """Load proxy settings from process variables and a local env file."""
        file_values = read_env_file(env_path)
        base_url = os.getenv("GEMINI_BASE_URL", file_values.get("url", "")).strip()
        api_key = os.getenv("GEMINI_API_KEY", file_values.get("key", "")).strip()
        model = os.getenv("GEMINI_MODEL", file_values.get("model", DEFAULT_MODEL)).strip()

        missing_names = [
            name
            for name, value in (("url/GEMINI_BASE_URL", base_url), ("key/GEMINI_API_KEY", api_key))
            if not value
        ]
        if missing_names:
            raise ValueError(f"Missing configuration: {', '.join(missing_names)}")

        return cls(base_url=base_url.rstrip("/"), api_key=api_key, model=model)


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


