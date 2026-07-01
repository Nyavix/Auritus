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
