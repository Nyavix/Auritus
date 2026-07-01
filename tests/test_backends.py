"""Unit tests for the pure, I/O-free parts of the inference backends.
These need only numpy/scipy/faster-whisper on the path — no display, no audio,
no GTK — so they run on a bare CI runner."""
from backends.whisper_cpp_backend import (
    MODEL_FILE_MAP,
    WhisperCppBackend,
    _build_multipart,
)

EXPECTED_MODELS = ["tiny.en", "base.en", "small.en", "medium.en", "large-v3"]


def test_model_file_map_covers_every_option():
    assert set(MODEL_FILE_MAP) == set(EXPECTED_MODELS)
    for fname in MODEL_FILE_MAP.values():
        assert fname.startswith("ggml-") and fname.endswith(".bin")


def test_build_multipart_shape():
    wav = b"RIFFfake"
    body, content_type = _build_multipart(wav, language="en")
    assert content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("boundary=", 1)[1]
    assert boundary.encode() in body
    assert wav in body
    assert b'name="file"' in body
    assert b'name="language"' in body
    assert body.rstrip().endswith(b"--" + boundary.encode() + b"--")


def test_ensure_model_file_short_circuits_on_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("backends.whisper_cpp_backend._models_dir", lambda: tmp_path)
    fname = MODEL_FILE_MAP["tiny.en"]
    (tmp_path / fname).write_bytes(b"not empty")

    def _boom(*a, **k):
        raise AssertionError("network was hit despite a cached model file")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    backend = WhisperCppBackend(log=lambda _m: None)
    result = backend._ensure_model_file("tiny.en")
    assert result == tmp_path / fname


def test_ensure_model_file_rejects_unknown_model(tmp_path, monkeypatch):
    monkeypatch.setattr("backends.whisper_cpp_backend._models_dir", lambda: tmp_path)
    backend = WhisperCppBackend(log=lambda _m: None)
    try:
        backend._ensure_model_file("does-not-exist")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown model")
