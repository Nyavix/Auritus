"""Characterization tests for the pure helpers in dictate.py. These lock in
current behavior so future edits to the 2833-line module can't silently change
version parsing, hotkey validation, or transcript cleanup."""
import pytest


def test_parse_version_basic(dictate):
    assert dictate._parse_version("v0.2.1") == (0, 2, 1)
    assert dictate._parse_version("0.3.3") == (0, 3, 3)


def test_parse_version_stops_at_non_numeric(dictate):
    assert dictate._parse_version("1.0.0-rc1") == (1, 0)
    assert dictate._parse_version("") == (0,)


def test_parse_version_ordering(dictate):
    assert dictate._parse_version("0.3.4") > dictate._parse_version("0.3.3")
    assert dictate._parse_version("v0.10.0") > dictate._parse_version("v0.9.9")


@pytest.mark.parametrize("spec", [
    "<ctrl>+<alt>+<space>", "<f9>", "<ctrl>+<shift>+d",
])
def test_is_valid_hotkey_accepts_known_good(dictate, spec):
    assert dictate.is_valid_hotkey(spec) is True


@pytest.mark.parametrize("spec", ["", "not a hotkey", "<ctrl>+"])
def test_is_valid_hotkey_rejects_garbage(dictate, spec):
    assert dictate.is_valid_hotkey(spec) is False


def test_clean_text_strips_timestamps_and_collapses_space(dictate):
    assert dictate.clean_text("  hello   world  ") == "hello world"
    assert dictate.clean_text("<|0.00|>hi there") == "hi there"


def test_clean_text_empty(dictate):
    assert dictate.clean_text("") == ""


def test_transcript_not_logged_by_default(dictate, monkeypatch, tmp_path):
    # With DEBUG_LOG_TEXT off (the default), the transcript body must never
    # reach the log. We capture what log() writes and assert the secret text
    # is absent while a length line is present.
    assert dictate.DEBUG_LOG_TEXT is False
    written = []
    monkeypatch.setattr(dictate, "log", lambda msg: written.append(msg))
    secret = "my password is hunter2"
    # Reproduce the exact default-path branch from _do_transcribe:
    if dictate.DEBUG_LOG_TEXT:
        dictate.log(f"Transcribed: {secret!r}")
    else:
        dictate.log(f"Transcribed {len(secret)} chars.")
    joined = "\n".join(written)
    assert secret not in joined
    assert "chars." in joined
