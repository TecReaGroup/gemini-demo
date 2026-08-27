from pathlib import Path

from gemini_demo.cli import build_parser, lyric_path_for


def test_lyric_path_uses_original_audio_name() -> None:
    assert lyric_path_for(Path("data/audio/一生爱你.m4a")) == Path("data/lyris/一生爱你.lrc")


def test_lyric_path_replaces_only_the_final_extension() -> None:
    assert lyric_path_for(Path("data/audio/live.version.mp3")) == Path(
        "data/lyris/live.version.lrc"
    )


def test_cli_uses_configured_strategy_by_default() -> None:
    assert build_parser().parse_args([]).strategy is None


def test_cli_can_override_configured_strategy() -> None:
    assert build_parser().parse_args(["--strategy", "native-inline"]).strategy == "native-inline"
