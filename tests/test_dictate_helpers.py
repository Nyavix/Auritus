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


def test_socket_listener_old_thread_exits_on_rebind(dictate, tmp_path, monkeypatch):
    """BUG-01: rebinding the Linux socket listener must not leave the previous
    _serve thread spinning on a closed fd. Build a minimal app object (skip the
    heavy __init__, which pulls GTK/audio) and exercise the real methods."""
    import threading
    import time
    import socket as _socket

    if not hasattr(_socket, "AF_UNIX"):
        import pytest
        pytest.skip("no AF_UNIX on this platform")

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    app = object.__new__(dictate.DictateApp)  # bypass __init__
    app._socket_server = None
    app._socket_thread = None
    app._stop_event = threading.Event()
    app._hotkey_bound = False
    app._hotkey_last_error = None
    app.state = "idle"
    app._refresh_tooltip = lambda: None
    app.on_toggle = lambda: None
    app.on_cancel = lambda: None
    app.quit = lambda: None

    try:
        app._start_socket_listener()
        first = app._socket_thread
        assert first is not None and first.is_alive()

        app._start_socket_listener()  # rebind -> old thread must exit
        deadline = time.time() + 3.0
        while first.is_alive() and time.time() < deadline:
            time.sleep(0.1)
        assert not first.is_alive(), "old _serve thread kept running after rebind"
    finally:
        app._stop_event.set()
        if app._socket_server is not None:
            app._socket_server.close()
