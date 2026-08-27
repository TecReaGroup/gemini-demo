from pathlib import Path

import pytest

from gemini_demo.config import DEFAULT_REQUEST_STRATEGY, Settings, read_toml_file

ENVIRONMENT_NAMES = (
    "GEMINI_BASE_URL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_REQUEST_STRATEGY",
)


def clear_gemini_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove process overrides so tests only exercise their temporary files."""
    for environment_name in ENVIRONMENT_NAMES:
        monkeypatch.delenv(environment_name, raising=False)


def test_settings_loads_request_strategy_from_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_gemini_environment(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text("url=https://proxy.example\nkey=secret\n", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text('[request]\nstrategy = "native-inline"\n', encoding="utf-8")

    settings = Settings.load(env_path=env_path, config_path=config_path)

    assert settings.request_strategy == "native-inline"


def test_settings_defaults_to_main_request_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_gemini_environment(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text("url=https://proxy.example\nkey=secret\n", encoding="utf-8")

    settings = Settings.load(env_path=env_path, config_path=tmp_path / "missing.toml")

    assert settings.request_strategy == DEFAULT_REQUEST_STRATEGY == "image-url"


def test_settings_rejects_unknown_request_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_gemini_environment(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text("url=https://proxy.example\nkey=secret\n", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text('[request]\nstrategy = "auto"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported request strategy"):
        Settings.load(env_path=env_path, config_path=config_path)


def test_read_toml_file_returns_request_table(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[request]\nstrategy = "input-audio"\n', encoding="utf-8")

    assert read_toml_file(config_path) == {"request": {"strategy": "input-audio"}}
